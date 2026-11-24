from django.utils import timezone
import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models


class Batch(models.Model):
    name = models.CharField(max_length=100, unique=True)
    minimum_percent = models.PositiveSmallIntegerField(default=75, validators=[MaxValueValidator(100)])

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(minimum_percent__gte=0, minimum_percent__lte=100), name="batch_threshold_range")]

    def __str__(self):
        return self.name


class Trainee(models.Model):
    account = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    code = models.SlugField(unique=True, help_text="Printed ID for manual entry.")
    badge = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    def __str__(self):
        return f"{self.name} ({self.code})"


class Session(models.Model):
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT)
    title = models.CharField(max_length=120)
    date = models.DateField()
    trainer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    closed = models.BooleanField(default=False, editable=False)

    def __str__(self):
        return f"{self.date} · {self.title}"


class Attendance(models.Model):
    session = models.ForeignKey(Session, on_delete=models.PROTECT)
    trainee = models.ForeignKey(Trainee, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session","trainee"], name="one_mark_per_session")]


class Approval(models.Model):
    trainee = models.OneToOneField(Trainee, on_delete=models.PROTECT)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    approved_at = models.DateTimeField(auto_now_add=True)
    attended = models.PositiveIntegerField()
    total = models.PositiveIntegerField()
    threshold = models.PositiveSmallIntegerField()
    trainee_name = models.CharField(max_length=100, default="", editable=False)
    trainee_code = models.CharField(max_length=50, default="", editable=False)
    batch_name = models.CharField(max_length=100, default="", editable=False)
    reviewer_name = models.CharField(max_length=150, default="", editable=False)
    approval_method = models.CharField(max_length=16, default="legacy_unknown", editable=False)
    snapshot_origin = models.CharField(max_length=16, default="reconstructed", editable=False)

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.trainee_name = self.trainee.name
            self.trainee_code = self.trainee.code
            self.batch_name = self.trainee.batch.name
            self.reviewer_name = self.reviewer.username
        super().save(*args, **kwargs)

    @property
    def certificate_reference(self):
        return f"TR-{self.pk:06d}"


    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(threshold__gte=0, threshold__lte=100), name="approval_threshold_range"),
            models.CheckConstraint(condition=models.Q(total__gt=0), name="approval_positive_total"),
            models.CheckConstraint(condition=models.Q(attended__lte=models.F("total")), name="approval_attended_within_total"),
        ]


class Correction(models.Model):
    session = models.ForeignKey(Session, on_delete=models.PROTECT)
    trainee = models.ForeignKey(Trainee, on_delete=models.PROTECT)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    present = models.BooleanField()
    reason = models.CharField(max_length=240)
    recorded_at = models.DateTimeField(auto_now_add=True)


class AuditEntry(models.Model):
    """Historical display values survive roster, batch and staff renames."""
    timestamp = models.DateTimeField(default=timezone.now)
    trainee_name = models.CharField(max_length=180)
    context = models.TextField()
    actor = models.CharField(max_length=180)
    reason = models.CharField(max_length=40)
    note = models.CharField(max_length=240, blank=True)
    seed_key = models.CharField(max_length=60, unique=True, null=True)

    class Meta:
        ordering = ['-timestamp', '-pk']
