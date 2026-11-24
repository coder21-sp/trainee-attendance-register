from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q, Value
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
from .roles import coordinator_required, is_coordinator


@login_required
def home(request):
    if Trainee.objects.filter(account=request.user).exists():
        return redirect("progress")
    can_coordinate = is_coordinator(request.user)
    sessions = Session.objects.select_related("batch", "trainer").order_by("-date", "id")
    if not can_coordinate:
        sessions = sessions.filter(trainer=request.user)
    return render(request, "home.html", {"sessions": sessions, "batches": Batch.objects.all() if can_coordinate else []})


@login_required
@transaction.atomic
def register(request, pk):
    session = get_object_or_404(Session, pk=pk, **({} if is_coordinator(request.user) else {"trainer":request.user}))
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


def evidence_summary(total, pending, attended, threshold):
    return {
        "total": total,
        "pending": pending,
        "attended": attended,
        "eligible": total > 0 and pending == 0 and attended * 100 >= total * threshold,
    }


def session_counts(batch_id):
    return Session.objects.filter(batch_id=batch_id).aggregate(
        total=Count("pk"), pending=Count("pk", filter=Q(closed=False)),
    )


def attendance_counts_by_trainee(marks):
    return marks.values("trainee_id").annotate(
        marked=Count("pk"),
        attended=Count("pk", filter=Q(session__closed=True)),
    )


def evidence(trainee):
    counts = session_counts(trainee.batch_id)
    attended = Attendance.objects.filter(
        trainee=trainee, session__batch_id=trainee.batch_id, session__closed=True,
    ).count()
    return evidence_summary(counts["total"], counts["pending"], attended, trainee.batch.minimum_percent)


@coordinator_required
def review(request, pk):
    batch = get_object_or_404(Batch, pk=pk)
    counts = session_counts(batch.pk)
    marks = Attendance.objects.filter(session__batch_id=batch.pk)
    attendance = {row["trainee_id"]: row["attended"] for row in attendance_counts_by_trainee(marks)}
    trainees = Trainee.objects.filter(batch=batch).select_related("approval__reviewer").order_by("name", "code")
    rows = [
        (trainee, evidence_summary(
            counts["total"], counts["pending"], attendance.get(trainee.pk, 0),
            batch.minimum_percent,
        ))
        for trainee in trainees
    ]
    return render(request,"review.html",{"batch":batch,"rows":rows,"reasons":REASONS})


@coordinator_required
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


@coordinator_required
def badge(request, pk):
    trainee = get_object_or_404(Trainee,pk=pk)
    response = HttpResponse(content_type="image/svg+xml")
    qrcode.make(str(trainee.badge),image_factory=qrcode.image.svg.SvgPathFillImage).save(response)
    return response


@login_required
def progress(request):
    trainee = get_object_or_404(Trainee.objects.select_related("batch", "approval"), account=request.user)
    quarantined = recovery_requires_review()
    context = {"trainee": trainee, "recovery_required": quarantined, "status": "Reconciliation required"}
    if not quarantined:
        sessions = list(Session.objects.filter(batch=trainee.batch).order_by("date", "pk"))
        marked = set(Attendance.objects.filter(trainee=trainee).values_list("session_id", flat=True))
        confirmed = sum(session.closed and session.pk in marked for session in sessions)
        pending = sum(not session.closed for session in sessions)
        approval = getattr(trainee, "approval", None)
        if approval:
            status = "Approved"
        elif pending or not sessions:
            status = "Pending registers"
        elif confirmed * 100 >= len(sessions) * trainee.batch.minimum_percent:
            status = "Eligible"
        else:
            status = "Below threshold"
        context.update(
            approval=approval, confirmed=confirmed, pending=pending, status=status,
            sessions=[(session, "Present" if session.pk in marked else "Absent" if session.closed else "Pending")
                      for session in sessions],
        )
    return render(request, "progress.html", context)


@login_required
def live(request, batch_id=None):
    if batch_id is not None and not is_coordinator(request.user):
        return HttpResponse(status=403)
    quarantined = recovery_requires_review()
    if batch_id is None:
        trainee = get_object_or_404(
            Trainee.objects.select_related("batch", "approval"), account=request.user,
        )
        sessions = list(Session.objects.filter(batch_id=trainee.batch_id).order_by("date", "pk"))
        marked_ids = set(Attendance.objects.filter(
            trainee_id=trainee.pk, session__batch_id=trainee.batch_id,
        ).values_list("session_id", flat=True))
        pending = sum(not session.closed for session in sessions)
        attended = sum(session.closed and session.pk in marked_ids for session in sessions)
        rows = [live_row(trainee, len(sessions), pending, len(marked_ids), attended,
                         trainee.batch.minimum_percent, quarantined)]
        session_data = [
            {"title": session.title, "closed": session.closed,
             "status": "Present" if session.pk in marked_ids else "Absent" if session.closed else "Pending"}
            for session in sessions
        ]
    else:
        batch = get_object_or_404(Batch, pk=batch_id)
        trainees = Trainee.objects.filter(batch_id=batch.pk).select_related("approval").order_by("pk")
        sessions = list(Session.objects.filter(batch_id=batch.pk).order_by("date", "pk"))
        attendance, session_marks = batch_mark_counts(batch.pk)
        pending = sum(not session.closed for session in sessions)
        rows = []
        for trainee in trainees:
            marked, attended = attendance.get(trainee.pk, (0, 0))
            rows.append(live_row(
                trainee, len(sessions), pending, marked, attended, batch.minimum_percent, quarantined,
            ))
        session_data = [
            {"title": session.title, "closed": session.closed, "count": session_marks.get(session.pk, 0)}
            for session in sessions
        ]
    return JsonResponse({"recovery_required": quarantined, "rows": rows, "sessions": session_data})


def batch_mark_counts(batch_id):
    marks = Attendance.objects.filter(session__batch_id=batch_id)
    by_trainee = attendance_counts_by_trainee(marks).annotate(scope=Value("trainee"))
    by_session = marks.values("session_id").annotate(
        scope=Value("session"), marked=Count("pk"), attended=Value(0),
    )
    # Both breakdowns see the same attendance snapshot even if a scan posts mid-poll.
    grouped = by_trainee.values_list("trainee_id", "scope", "marked", "attended").union(
        by_session.values_list("session_id", "scope", "marked", "attended"), all=True,
    )
    attendance = {}
    session_marks = {}
    for key, scope, marked, attended in grouped:
        if scope == "trainee":
            attendance[key] = (marked, attended)
        else:
            session_marks[key] = marked
    return attendance, session_marks


def live_row(trainee, total, pending, marked, attended, threshold, quarantined):
    summary = evidence_summary(total, pending, attended, threshold)
    if quarantined:
        status = "Reconciliation required"
    elif hasattr(trainee, "approval"):
        status = "Approved"
    elif not total or pending:
        status = "Pending registers"
    elif summary["eligible"]:
        status = "Eligible"
    else:
        status = "Below threshold"
    return {
        "id": trainee.pk, "name": trainee.name, "code": trainee.code, "attended": attended,
        "marked": marked, "total": total, "status": status,
    }


@coordinator_required
def id_pass(request, pk):
    return render(request,"pass.html",{"trainee":get_object_or_404(Trainee,pk=pk)})


@login_required
def certificate(request, pk):
    approval = get_object_or_404(Approval.objects.select_related("trainee__batch","reviewer"), trainee_id=pk)
    if not is_coordinator(request.user) and approval.trainee.account_id != request.user.pk:
        return HttpResponse(status=403)
    if recovery_requires_review():
        return recovery_conflict()
    response = HttpResponse(render_certificate(approval), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="training-certificate-{pk}.pdf"'
    return response
