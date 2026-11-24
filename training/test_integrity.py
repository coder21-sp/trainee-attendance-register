from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from .models import Approval, Attendance, Batch, Session, Trainee


class DatabaseIntegrityTests(TestCase):
    def setUp(self):
        self.reviewer = get_user_model().objects.create(username="integrity-reviewer")
        self.batch = Batch.objects.create(name="Integrity batch")
        self.other = Batch.objects.create(name="Other batch")
        self.trainee = Trainee.objects.create(batch=self.batch, name="Test trainee", code="IT-1")
        self.session = Session.objects.create(batch=self.batch, title="Workshop",
                                              date=timezone.localdate(), trainer=self.reviewer)
        self.other_session = Session.objects.create(batch=self.other, title="Other workshop",
                                                    date=timezone.localdate(), trainer=self.reviewer)

    def test_batch_threshold_above_100_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Batch.objects.create(name="Invalid threshold", minimum_percent=101)

    def test_batch_bulk_update_above_100_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Batch.objects.filter(pk=self.batch.pk).update(minimum_percent=101)

    def create_approval(self, **overrides):
        values = dict(trainee=self.trainee, reviewer=self.reviewer,
                      attended=1, total=1, threshold=75)
        values.update(overrides)
        return Approval.objects.create(**values)

    def test_approval_rejects_invalid_attendance_count(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_approval(attended=6, total=5)

    def test_approval_rejects_zero_total(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_approval(attended=0, total=0)

    def test_approval_rejects_threshold_above_100(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_approval(threshold=101)

    def test_cross_batch_attendance_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Attendance.objects.create(trainee=self.trainee, session=self.other_session)

    def test_cross_batch_attendance_update_rejected(self):
        mark = Attendance.objects.create(trainee=self.trainee, session=self.session)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Attendance.objects.filter(pk=mark.pk).update(session=self.other_session)

    def test_trainee_move_cannot_invalidate_existing_mark(self):
        Attendance.objects.create(trainee=self.trainee, session=self.session)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Trainee.objects.filter(pk=self.trainee.pk).update(batch=self.other)

    def test_session_move_cannot_invalidate_existing_mark(self):
        Attendance.objects.create(trainee=self.trainee, session=self.session)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Session.objects.filter(pk=self.session.pk).update(batch=self.other)

    def test_valid_boundary_values_accepted(self):
        Batch.objects.filter(pk=self.batch.pk).update(minimum_percent=100)
        approval = self.create_approval(attended=0, total=1, threshold=0)
        self.assertEqual(approval.attended, 0)
        self.assertEqual(approval.threshold, 0)
        mark = Attendance.objects.create(trainee=self.trainee, session=self.session)
        self.assertIsNotNone(mark.pk)
