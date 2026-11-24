from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from .models import Approval, Attendance, Batch, Session, Trainee


class ApprovedBatchTests(TestCase):
    def setUp(self):
        self.coordinator = get_user_model().objects.create(
            username="batch-coordinator", is_superuser=True, is_staff=True)
        self.batch = Batch.objects.create(name="Approved batch")
        self.other = Batch.objects.create(name="Unapproved batch")
        self.trainee = Trainee.objects.create(batch=self.batch, name="First trainee", code="LOCK-1")
        self.second = Trainee.objects.create(batch=self.batch, name="Second trainee", code="LOCK-2")
        self.session = Session.objects.create(
            batch=self.batch, title="Workshop", date=timezone.localdate(),
            trainer=self.coordinator, closed=True)
        self.mark = Attendance.objects.create(trainee=self.trainee, session=self.session)
        Attendance.objects.create(trainee=self.second, session=self.session)
        self.client.force_login(self.coordinator)
        self.client.post(f"/approve/{self.trainee.pk}/")
        self.assertTrue(Approval.objects.filter(trainee=self.trainee).exists())

    def test_cannot_add_session_after_approval(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Session.objects.create(batch=self.batch, title="New workshop",
                                   date=timezone.localdate(), trainer=self.coordinator)

    def test_cannot_change_session_title(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Session.objects.filter(pk=self.session.pk).update(title="Changed workshop")

    def test_cannot_change_session_date(self):
        from datetime import timedelta
        with self.assertRaises(IntegrityError), transaction.atomic():
            Session.objects.filter(pk=self.session.pk).update(date=self.session.date + timedelta(days=1))

    def test_cannot_reopen_approved_batch_session(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Session.objects.filter(pk=self.session.pk).update(closed=False)

    def test_cannot_change_threshold_after_approval(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Batch.objects.filter(pk=self.batch.pk).update(minimum_percent=50)

    def test_cannot_add_trainee_to_approved_batch(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Trainee.objects.create(batch=self.batch, name="New trainee", code="LOCK-3")

    def test_cannot_move_unapproved_trainee_into_locked_batch(self):
        outsider = Trainee.objects.create(batch=self.other, name="Outsider", code="OUT-1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Trainee.objects.filter(pk=outsider.pk).update(batch=self.batch)

    def test_cannot_remove_approved_attendance_directly(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Attendance.objects.filter(pk=self.mark.pk).delete()

    def test_unapproved_trainee_can_still_be_corrected(self):
        response = self.client.post(f"/sessions/{self.session.pk}/", {
            "action": "correct", "code": self.second.code, "status": "absent",
            "reason": "Roster Correction",
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Attendance.objects.filter(trainee=self.second, session=self.session).exists())

    def test_other_eligible_trainee_can_still_be_approved(self):
        self.client.post(f"/approve/{self.second.pk}/")
        self.assertTrue(Approval.objects.filter(trainee=self.second).exists())

    def test_unapproved_batch_allows_session_creation(self):
        session = Session.objects.create(batch=self.other, title="New workshop",
                                         date=timezone.localdate(), trainer=self.coordinator)
        self.assertIsNotNone(session.pk)
