import csv

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


def record(user, trainee, action, details, session=None):
    role = "Coordinator" if user.is_superuser else "Trainer"
    context = f"{trainee.batch} · {session} · {action}" if session else f"{trainee.batch} · {action}"
    return AuditEntry.objects.create(trainee_name=str(trainee), context=context,
                                     actor=f"{user.username} ({role})", reason=details[0], note=details[1])


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
