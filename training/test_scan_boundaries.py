from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Attendance, AuditEntry, Batch, Session, Trainee


class ScanBoundaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.trainer = users.create_user(username="assigned-scanner")
        cls.other_trainer = users.create_user(username="other-scanner")
        today = timezone.localdate()
        batch = Batch.objects.create(name="Scanning cohort")
        cls.trainee = Trainee.objects.create(batch=batch, name="Assigned trainee", code="SCAN-1")
        other_batch = Batch.objects.create(name="Different cohort")
        cls.other_trainee = Trainee.objects.create(batch=other_batch, name="Other trainee", code="SCAN-2")
        cls.current_session = Session.objects.create(
            batch=batch, date=today, trainer=cls.trainer, title="Current workshop",
        )
        cls.future_session = Session.objects.create(
            batch=batch, date=today + timedelta(days=1), trainer=cls.trainer, title="Future workshop",
        )

    def scan(self, user, session, trainee):
        self.client.force_login(user)
        response = self.client.post(
            reverse("mark-api", args=[session.pk]),
            {"source": "scan", "code": str(trainee.badge)},
            headers={"accept": "application/json"},
        )
        self.assertFalse(Attendance.objects.exists())
        self.assertFalse(AuditEntry.objects.exists())
        return response

    def test_valid_badge_from_another_batch_is_rejected(self):
        response = self.scan(self.trainer, self.current_session, self.other_trainee)
        self.assertEqual(response.status_code, 400)
        self.assertIs(response.json()["saved"], False)

    def test_valid_badge_cannot_mark_a_future_session(self):
        response = self.scan(self.trainer, self.future_session, self.trainee)
        self.assertEqual(response.status_code, 400)
        self.assertIs(response.json()["saved"], False)

    def test_unassigned_trainer_cannot_scan_a_valid_badge(self):
        response = self.scan(self.other_trainer, self.current_session, self.trainee)
        self.assertEqual(response.status_code, 404)
