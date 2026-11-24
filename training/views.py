from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db import transaction
from .audit import REASONS, explanation, record_event
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone
import qrcode
import qrcode.image.svg
import uuid

from .models import Approval, Attendance, Batch, Session, Trainee
from .certificates import render_certificate
from .recovery import recovery_requires_review, recovery_conflict

coordinator = user_passes_test(lambda user: user.is_superuser)


@login_required
def home(request):
    if Trainee.objects.filter(account=request.user).exists():
        return redirect("progress")
    sessions = Session.objects.select_related("batch").order_by("-date","id")
    if not request.user.is_superuser:
        sessions = sessions.filter(trainer=request.user)
    return render(request, "home.html", {"sessions": sessions, "batches": Batch.objects.all() if request.user.is_superuser else []})


@login_required
@transaction.atomic
def register(request, pk):
    session = get_object_or_404(Session, pk=pk, **({} if request.user.is_superuser else {"trainer":request.user}))
    if request.method == "POST":
        if recovery_requires_review():
            return recovery_conflict()
        if request.POST.get("action") == "correct":
            trainee = get_object_or_404(Trainee, code=request.POST.get("code"), batch=session.batch)
            details = explanation(request.POST)
            present = request.POST.get("status") == "present"
            existing = Attendance.objects.filter(session=session, trainee=trainee)
            if Approval.objects.filter(trainee=trainee).exists():
                messages.error(request, "This trainee already has a certificate approval.")
            elif not details or request.POST.get("status") not in {"present","absent"} or session.date > timezone.localdate():
                messages.error(request, "Choose a current or past session and enter a correction reason.")
            elif existing.exists() == present:
                messages.info(request, "Attendance already matches.")
            else:
                if present:
                    Attendance.objects.create(session=session, trainee=trainee)
                else:
                    existing.delete()
                record_event(user=request.user, batch=session.batch, trainee=trainee,
                             session=session, action="attendance_corrected",
                             label="Mark added" if present else "Mark removed",
                             source="correction", previous=not present, new=present,
                             details=details)
                messages.success(request, "Correction recorded.")
            return redirect("register", pk=pk)
        if session.closed or session.date > timezone.localdate():
            messages.error(request, "This session is closed or scheduled for a future date.")
        elif request.POST.get("action") == "close":
            session.closed = True
            session.save(update_fields=["closed"])
            record_event(user=request.user, batch=session.batch, session=session,
                         action="register_closed", label="Register closed",
                         source="register", previous=False, new=True)
            messages.success(request, "Register closed. Unmarked trainees now count as absent.")
        else:
            value = request.POST.get("code","").strip()
            scanned = request.POST.get("source") == "scan"
            details = explanation(request.POST)
            trainee = None
            if scanned:
                try:
                    badge_id = uuid.UUID(value)
                except ValueError:
                    badge_id = None
                if badge_id:
                    trainee = Trainee.objects.filter(badge=badge_id, batch=session.batch).first()
            else:
                trainee = Trainee.objects.filter(code=value, batch=session.batch).first()
            if not scanned and not details:
                messages.error(request, "Select a manual reason and keep the note within 240 characters.")
            elif trainee is None:
                messages.error(request, "Unknown ID for this batch.")
            else:
                _, created = Attendance.objects.get_or_create(session=session, trainee=trainee)
                if created:
                    record_event(user=request.user, batch=session.batch, trainee=trainee,
                                 session=session, action="attendance_marked",
                                 label="QR present mark" if scanned else "Manual present mark",
                                 source="qr" if scanned else "manual", previous=False,
                                 new=True, details=None if scanned else details)
                messages.success(request, f"{trainee.name}: " + ("present." if created else "already marked."))
        if request.headers.get("Accept") == "application/json":
            alerts = list(messages.get_messages(request))
            failed = any(alert.level >= messages.ERROR for alert in alerts)
            return JsonResponse({"message": str(alerts[-1]) if alerts else "", "saved": not failed},
                                status=400 if failed else 200)
        return redirect("register", pk=pk)
    return render(request, "register.html", {"session":session, "reasons": REASONS, "marks":Attendance.objects.filter(session=session).select_related("trainee")})


def evidence(trainee):
    sessions = Session.objects.filter(batch=trainee.batch)
    total = sessions.count()
    pending = sessions.filter(closed=False).count()
    attended = Attendance.objects.filter(trainee=trainee, session__in=sessions.filter(closed=True)).count()
    return dict(total=total, pending=pending, attended=attended, eligible=total>0 and pending==0 and attended*100>=total*trainee.batch.minimum_percent)


@coordinator
def review(request, pk):
    batch = get_object_or_404(Batch, pk=pk)
    rows = [(t,evidence(t)) for t in Trainee.objects.filter(batch=batch).select_related("batch","approval").order_by("name","code")]
    return render(request,"review.html",{"batch":batch,"rows":rows,"reasons":REASONS})


@coordinator
@require_POST
@transaction.atomic
def approve(request, pk):
    if recovery_requires_review():
        return recovery_conflict()
    trainee = get_object_or_404(Trainee,pk=pk)
    result = evidence(trainee)
    override = request.POST.get("action") == "override"
    details = explanation(request.POST)
    if override and (not details or result["eligible"] or result["pending"] or not result["total"]):
        messages.error(request, "Overrides require closed registers, below-threshold attendance and a selected reason.")
    elif result["eligible"] or override:
        approval, created = Approval.objects.get_or_create(trainee=trainee, defaults=dict(reviewer=request.user, attended=result["attended"], total=result["total"], threshold=trainee.batch.minimum_percent, approval_method="override" if override else "standard", snapshot_origin="original"))
        if created:
            label = "Certificate override" if override else "Certificate approved"
            record_event(user=request.user, batch=trainee.batch, trainee=trainee,
                         action="certificate_approved", label=label,
                         source="override" if override else "standard", previous=None,
                         new={"approval_id": approval.pk, "attended": approval.attended,
                              "total": approval.total, "threshold": approval.threshold},
                         details=details if override else None)
        messages.success(request,"Certificate approval recorded.")
    else:
        messages.error(request,"Attendance is pending or below this batch's threshold.")
    return redirect("review",pk=trainee.batch_id)


@coordinator
def badge(request, pk):
    trainee = get_object_or_404(Trainee,pk=pk)
    response = HttpResponse(content_type="image/svg+xml")
    qrcode.make(str(trainee.badge),image_factory=qrcode.image.svg.SvgPathFillImage).save(response)
    return response


@login_required
def progress(request):
    trainee = get_object_or_404(Trainee.objects.select_related("batch"), account=request.user)
    return render(request, "progress.html", {"trainee":trainee})


@login_required
def live(request, batch_id=None):
    from django.http import JsonResponse
    if batch_id is None:
        trainee = get_object_or_404(Trainee, account=request.user)
        trainees = [trainee]
        batch = trainee.batch
    else:
        if not request.user.is_superuser:
            return HttpResponse(status=403)
        batch = get_object_or_404(Batch, pk=batch_id)
        trainees = Trainee.objects.filter(batch=batch).select_related("batch","approval")
    sessions = list(Session.objects.filter(batch=batch).order_by("date","pk"))
    marks = set(Attendance.objects.filter(session__batch=batch).values_list("session_id","trainee_id"))
    closed = {s.pk for s in sessions if s.closed}
    rows = []
    quarantined = recovery_requires_review()
    for t in trainees:
        attended = sum((sid,t.pk) in marks for sid in closed)
        approved = hasattr(t,"approval")
        eligible = bool(sessions) and len(closed)==len(sessions) and attended*100 >= len(sessions)*batch.minimum_percent
        rows.append({"id":t.pk, "name":t.name, "code":t.code, "attended":attended,
                     "marked":sum((s.pk,t.pk) in marks for s in sessions), "total":len(sessions),
                     "status":"Reconciliation required" if quarantined else "Approved" if approved else "Pending registers" if not sessions or len(closed)<len(sessions) else "Eligible" if eligible else "Below threshold"})
    return JsonResponse({"recovery_required": quarantined, "rows":rows,"sessions":[{"title":s.title,"closed":s.closed,
        "count":sum(sid==s.pk for sid,_ in marks)} for s in sessions] if batch_id else [
        {"title":s.title,"status":"Present" if (s.pk,trainee.pk) in marks else "Absent" if s.closed else "Pending"} for s in sessions]})


@coordinator
def id_pass(request, pk):
    return render(request,"pass.html",{"trainee":get_object_or_404(Trainee,pk=pk)})


@login_required
def certificate(request, pk):
    approval = get_object_or_404(Approval.objects.select_related("trainee__batch","reviewer"), trainee_id=pk)
    if not request.user.is_superuser and approval.trainee.account_id != request.user.pk:
        return HttpResponse(status=403)
    if recovery_requires_review():
        return recovery_conflict()
    response = HttpResponse(render_certificate(approval), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="training-certificate-{pk}.pdf"'
    return response
