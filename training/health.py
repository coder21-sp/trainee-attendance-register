import logging

from django.db import DatabaseError
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .models import LoginAttemptBucket
from .recovery import recovery_requires_review


logger = logging.getLogger(__name__)


@require_safe
@never_cache
def liveness(request):
    return JsonResponse({"status": "ok"})


@require_safe
@never_cache
def readiness(request):
    try:
        available = not recovery_requires_review()
        if available:
            LoginAttemptBucket.objects.exists()
    except DatabaseError:
        logger.warning("Register readiness database check failed")
        available = False
    if available:
        return JsonResponse({"status": "ready"})
    return JsonResponse({"status": "unavailable"}, status=503)
