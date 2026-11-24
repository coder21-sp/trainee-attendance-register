"""A restore marker is append-only and covered by existing audit receipts.

A recovered copy stays locked until operational evidence has been independently
reconciled. There is deliberately no unchecked web unlock.
"""
from django.http import JsonResponse
from .models import AuditEntry

WARNING = "Reconciliation required: restored records may be incomplete. Attendance and approvals are locked."


def recovery_requires_review():
    return AuditEntry.objects.filter(reason="Recovery required").exists()


def recovery_context(request):
    return {"recovery_required": request.user.is_authenticated and recovery_requires_review()}


def recovery_conflict():
    return JsonResponse({"message": WARNING, "saved": False, "recovery_required": True}, status=409)
