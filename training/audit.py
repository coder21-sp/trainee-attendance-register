import csv
import json

from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_safe

from .models import AuditEntry

REASONS = ("QR Camera Issue", "Medical Leave", "Official Plant Duty", "Network Error", "Roster Correction")
HEADINGS = ("Timestamp (IST)", "Trainee Name", "Session/Action", "Changed By", "Reason", "Note")


def explanation(post):
    reason = post.get("reason", "")
    note = post.get("note", "").strip()
    return (reason, note) if reason in REASONS and len(note) <= 240 else None


def record_event(*, user, batch, action, label, source, previous, new,
                 trainee=None, session=None, details=None):
    """Append structured evidence in the existing receipt-covered context."""
    role = "Coordinator" if user.is_superuser else "Trainer"
    payload = {
        "version": 1, "action": action, "source": source,
        "actor_id": user.pk, "actor_role": role, "batch_id": batch.pk,
        "trainee_id": trainee.pk if trainee else None,
        "session_id": session.pk if session else None,
        "previous": previous, "new": new,
    }
    label_text = " · ".join(str(value) for value in (batch, session, label) if value is not None)
    context = " ".join(label_text.splitlines()) + "\n" + json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    reason, note = details or (label, "")
    return AuditEntry.objects.create(
        trainee_name=str(trainee) if trainee else "(Entire register)",
        context=context, actor=f"{user.username} ({role})", reason=reason, note=note,
    )


def cells(entry):
    return (timezone.localtime(entry.timestamp).strftime("%Y-%m-%d %H:%M:%S"),
            entry.trainee_name, entry.context, entry.actor, entry.reason, entry.note)


@user_passes_test(lambda user: user.is_superuser)
@require_safe
def audit_log(request, export=False):
    entries = AuditEntry.objects.all()
    if export:
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="attendance-audit.csv"'
        writer = csv.writer(response)
        writer.writerow(HEADINGS)
        for entry in entries.iterator():
            writer.writerow(["'" + s if s.lstrip().startswith(("=", "+", "-", "@")) or s.startswith(("\t","\r","\n")) else s for s in cells(entry)])
        return response
    page = Paginator(entries, 50).get_page(request.GET.get("page"))
    return render(request, "audit.html", {"headers": HEADINGS, "rows": map(cells,page), "page":page})
