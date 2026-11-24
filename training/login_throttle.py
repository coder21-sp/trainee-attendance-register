from datetime import timedelta
from functools import wraps
from ipaddress import IPv6Address, ip_address, ip_network
from math import ceil
from unicodedata import normalize

from django.contrib.admin.sites import AdminSite
from django.db import transaction
from django.db.models import F
from django.http import HttpResponse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect

from .models import LoginAttemptBucket


WINDOW = timedelta(minutes=15)
ACCOUNT_LIMIT = 5
ADDRESS_LIMIT = 30


def client_address(request):
    try:
        address = ip_address(request.META.get("REMOTE_ADDR", ""))
    except ValueError:
        return "unknown"
    if isinstance(address, IPv6Address):
        if address.ipv4_mapped:
            return str(address.ipv4_mapped)
        return str(ip_network((address, 64), strict=False))
    return str(address)


def bucket_keys(request):
    address = client_address(request)
    username = normalize("NFKC", request.POST.get("username", "")[:150]).strip().casefold()
    return (
        salted_hmac("training.login.address.v1", address, algorithm="sha256").hexdigest(),
        salted_hmac("training.login.account.v1", f"{address}\0{username}", algorithm="sha256").hexdigest(),
    )


@transaction.atomic
def reserve_attempt(address_key, account_key):
    now = timezone.now()
    LoginAttemptBucket.objects.filter(expires_at__lte=now).delete()
    buckets = LoginAttemptBucket.objects.in_bulk([address_key, account_key])
    retry_times = [
        buckets[key].expires_at
        for key, limit in ((address_key, ADDRESS_LIMIT), (account_key, ACCOUNT_LIMIT))
        if key in buckets and buckets[key].attempts >= limit
    ]
    if retry_times:
        return ceil((max(retry_times) - now).total_seconds()), None

    for key in (address_key, account_key):
        bucket = buckets.get(key) or LoginAttemptBucket(key=key, expires_at=now + WINDOW)
        bucket.attempts += 1
        bucket.save()
        buckets[key] = bucket
    return 0, (buckets[address_key], buckets[account_key])


@transaction.atomic
def clear_successful_attempt(address_bucket, account_bucket):
    LoginAttemptBucket.objects.filter(
        key=address_bucket.key, expires_at=address_bucket.expires_at, attempts__gt=0,
    ).update(attempts=F("attempts") - 1)
    # Leave newer attempts intact if another request updated the same bucket.
    LoginAttemptBucket.objects.filter(
        key=account_bucket.key, expires_at=account_bucket.expires_at,
        attempts=account_bucket.attempts,
    ).delete()


def throttle_login(view):
    @wraps(view)
    @never_cache
    @csrf_protect
    def wrapped(request, *args, **kwargs):
        if request.method != "POST":
            return view(request, *args, **kwargs)

        retry_after, reservation = reserve_attempt(*bucket_keys(request))
        if retry_after:
            return HttpResponse(
                "Too many sign-in attempts. Try again later.", status=429,
                content_type="text/plain", headers={"Retry-After": str(retry_after)},
            )

        response = view(request, *args, **kwargs)
        if response.status_code == 302 and request.user.is_authenticated:
            clear_successful_attempt(*reservation)
        return response

    return wrapped


class ThrottledAdminSite(AdminSite):
    @method_decorator(throttle_login)
    def login(self, request, extra_context=None):
        return super().login(request, extra_context)
