"""Keep recovered registers locked until a coordinator reviews the latest restore."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .models import AuditEntry

WARNING = "Reconciliation required: restored records may be incomplete. Attendance and approvals are locked."


def pending_restore():
    marker = AuditEntry.objects.filter(reason="Recovery required").order_by("-pk").first()
    if marker and not AuditEntry.objects.filter(seed_key=f"recovery-reviewed:{marker.pk}", reason="Recovery reviewed", pk__gt=marker.pk).exists():
        return marker
    return None


def recovery_requires_review():
    return pending_restore() is not None


def recovery_context(request):
    return {"recovery_required": request.user.is_authenticated and recovery_requires_review()}


def recovery_conflict():
    return JsonResponse({"message": WARNING, "saved": False, "recovery_required": True}, status=409)


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def review_recovery(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    marker = pending_restore()
    if request.method == "GET":
        return render(request, "recovery_review.html", {"marker":marker})
    if not marker or request.POST.get("marker") != str(marker.pk):
        return render(request, "recovery_review.html", {"marker":marker, "error":"Review status changed. Check the latest restore."}, status=409)
    evidence = request.POST.get("evidence","").strip()
    reason = request.POST.get("reason","").strip()
    if not evidence or len(evidence)>240 or not reason or len(reason)>240 or request.POST.get("verified") != "yes":
        return render(request, "recovery_review.html", {"marker":marker, "error":"Record the evidence, explain your decision, and confirm reconciliation."}, status=400)
    AuditEntry.objects.create(
        trainee_name="(Entire register)", actor=f"{request.user.username} (Coordinator)",
        context=f"Recovery review · restore #{marker.pk} · Evidence checked: {evidence}",
        reason="Recovery reviewed", note=reason, seed_key=f"recovery-reviewed:{marker.pk}")
    return redirect("audit")
