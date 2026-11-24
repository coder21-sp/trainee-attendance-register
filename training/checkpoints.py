"""Compare a coordinator's separately retained receipt with the audit history."""
import hashlib
import json

from django.contrib.auth.decorators import user_passes_test
from django.core import signing
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .models import AuditEntry

SALT = "training.audit.receipt.v1"


@user_passes_test(lambda user: user.is_superuser)
@require_POST
@never_cache
def checkpoint(request):
    receipt = request.POST.get("receipt", "")
    previous = None
    if receipt:
        try:
            if len(receipt) > 2048:
                raise ValueError()
            previous = signing.loads(receipt, salt=SALT)
        except (signing.BadSignature, ValueError):
            return JsonResponse({"error": "Receipt could not be authenticated. Check the file and server signing key."}, status=400)

    digest = hashlib.sha256(b"training.audit.v1\n")
    count = 0
    matches = previous is None or previous == [0, digest.hexdigest()]
    fields = ("id", "timestamp", "trainee_name", "context", "actor", "reason", "note", "seed_key")
    for row in AuditEntry.objects.order_by("pk").values_list(*fields).iterator():
        values = [row[0], row[1].isoformat(), *row[2:]]
        digest.update(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode() + b"\n")
        count += 1
        if previous and count == previous[0]:
            matches = previous == [count, digest.hexdigest()]

    if not matches:
        return JsonResponse({"error": "Audit history differs from the saved receipt. Preserve both copies and investigate before using this register."}, status=409)
    return JsonResponse({"count": count, "receipt": signing.dumps([count, digest.hexdigest()], salt=SALT)})
