import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models


class Batch(models.Model):
    name = models.CharField(max_length=100, unique=True)
    minimum_percent = models.PositiveSmallIntegerField(default=75, validators=[MaxValueValidator(100)])

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


class Correction(models.Model):
    session = models.ForeignKey(Session, on_delete=models.PROTECT)
    trainee = models.ForeignKey(Trainee, on_delete=models.PROTECT)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    present = models.BooleanField()
    reason = models.CharField(max_length=240)
    recorded_at = models.DateTimeField(auto_now_add=True)
