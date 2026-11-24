"""Keep recovered registers locked until a coordinator reviews the latest restore."""
import hashlib
import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_safe

from .models import AuditEntry
from .roles import is_coordinator

WARNING = "Reconciliation required: restored records may be incomplete. Attendance and approvals are locked."
RECONCILED = "Recovery reconciled"


def event_payload(entry):
    try:
        payload = json.loads(entry.context.split("\n", 1)[1])
    except (IndexError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def valid_marker(marker):
    payload = event_payload(marker)
    return (
        marker.actor == "Restore command"
        and type(payload.get("version")) is int and payload["version"] == 1
        and payload.get("action") == "recovery_required"
        and payload.get("source") == "restore"
        and type(payload.get("retained_event_count")) is int
        and payload["retained_event_count"] >= 0
        and isinstance(payload.get("backup_reference"), str)
        and bool(payload["backup_reference"])
    )


def marker_digest(marker):
    fields = [marker.pk, marker.timestamp.isoformat(), marker.trainee_name, marker.context,
              marker.actor, marker.reason, marker.note, marker.seed_key]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()


def pending_restore():
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM training_pending_recovery")
        row = cursor.fetchone()
    return AuditEntry.objects.get(pk=row[0]) if row else None


def recovery_requires_review():
    with connection.cursor() as cursor:
        cursor.execute("SELECT EXISTS (SELECT 1 FROM training_pending_recovery)")
        return bool(cursor.fetchone()[0])


def recovery_context(request):
    return {"recovery_required": request.user.is_authenticated and recovery_requires_review()}


def recovery_conflict():
    return JsonResponse({"message": WARNING, "saved": False, "recovery_required": True}, status=409)


@login_required
@require_safe
def review_recovery(request):
    if not is_coordinator(request.user):
        raise PermissionDenied
    return render(request, "recovery_review.html", {"marker": pending_restore()})
