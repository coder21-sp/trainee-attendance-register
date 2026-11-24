import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from .models import Approval, Attendance, AuditEntry, Batch, Session, Trainee


class AuditEventTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.trainer = users.create(username="event-trainer")
        self.coordinator = users.create(username="event-coordinator", is_superuser=True)
        self.batch = Batch.objects.create(name="Event batch")
        self.trainee = Trainee.objects.create(batch=self.batch, name="Event trainee", code="EV-1")
        self.session = Session.objects.create(batch=self.batch, title="Workshop",
                                              date=timezone.localdate(), trainer=self.trainer)
        self.route = f"/sessions/{self.session.pk}/"
        self.approve = f"/approve/{self.trainee.pk}/"
        self.client.force_login(self.trainer)

    def scan(self):
        return self.client.post(self.route, {"source": "scan", "code": str(self.trainee.badge)})

    def event(self, action):
        # Structured payload is embedded in the immutable context so existing
        # signed receipts and restore tooling also cover the new metadata.
        rows = AuditEntry.objects.filter(context__contains='"action":"' + action + '"')
        self.assertEqual(rows.count(), 1)
        return json.loads(rows.get().context.split("\n", 1)[1])

    def test_qr_mark_has_attributed_event(self):
        self.scan()
        self.assertTrue(Attendance.objects.filter(trainee=self.trainee).exists())
        data = self.event("attendance_marked")
        self.assertEqual(data["source"], "qr")
        self.assertEqual(data["actor_id"], self.trainer.pk)
        self.assertEqual(data["trainee_id"], self.trainee.pk)
        self.assertEqual(data["batch_id"], self.batch.pk)
        self.assertEqual(data["session_id"], self.session.pk)
        self.assertEqual((data["previous"], data["new"]), (False, True))

    def test_duplicate_scan_has_one_event(self):
        self.scan()
        self.scan()
        self.assertEqual(Attendance.objects.count(), 1)
        self.assertEqual(AuditEntry.objects.count(), 1)

    def test_manual_mark_has_structured_event(self):
        self.client.post(self.route, {"code": self.trainee.code, "reason": "Network Error"})
        data = self.event("attendance_marked")
        self.assertEqual(data["source"], "manual")
        self.assertEqual(AuditEntry.objects.get().reason, "Network Error")

    def test_correction_records_previous_and_new_state(self):
        self.scan()
        self.client.post(self.route, {"action": "correct", "code": self.trainee.code,
                                      "status": "absent", "reason": "Roster Correction"})
        data = self.event("attendance_corrected")
        self.assertEqual((data["previous"], data["new"]), (True, False))
        self.assertFalse(Attendance.objects.exists())

    def test_register_closure_is_audited_once(self):
        for _ in range(2):
            self.client.post(self.route, {"action": "close"})
        self.session.refresh_from_db()
        self.assertTrue(self.session.closed)
        data = self.event("register_closed")
        self.assertEqual(data["session_id"], self.session.pk)
        self.assertEqual(data["actor_id"], self.trainer.pk)
        self.assertEqual(AuditEntry.objects.count(), 1)

    def test_standard_approval_is_audited_once(self):
        self.scan()
        self.client.post(self.route, {"action": "close"})
        self.client.force_login(self.coordinator)
        for _ in range(2):
            self.client.post(self.approve)
        data = self.event("certificate_approved")
        self.assertEqual(data["source"], "standard")
        self.assertEqual(data["actor_id"], self.coordinator.pk)
        self.assertEqual(Approval.objects.count(), 1)

    def test_override_is_structured_and_preserves_reason(self):
        self.client.post(self.route, {"action": "close"})
        self.client.force_login(self.coordinator)
        self.client.post(self.approve, {"action": "override", "reason": "Medical Leave"})
        data = self.event("certificate_approved")
        self.assertEqual(data["source"], "override")
        self.assertEqual(AuditEntry.objects.filter(reason="Medical Leave").count(), 1)

    def test_invalid_scan_does_not_log_success(self):
        self.client.post(self.route, {"source": "scan", "code": "invalid"})
        self.assertFalse(Attendance.objects.exists())
        self.assertFalse(AuditEntry.objects.exists())

    def test_qr_mark_rolls_back_if_audit_write_fails(self):
        with patch("training.audit.AuditEntry.objects.create", side_effect=IntegrityError("audit unavailable")):
            with self.assertRaises(IntegrityError):
                self.scan()
        self.assertFalse(Attendance.objects.exists())
        self.assertFalse(AuditEntry.objects.exists())

    def test_existing_receipt_remains_valid_after_new_events(self):
        self.client.force_login(self.coordinator)
        AuditEntry.objects.create(trainee_name="Legacy", context="Legacy action",
                                  actor="Legacy trainer", reason="Medical Leave")
        receipt = self.client.post("/audit/checkpoint/").json()["receipt"]
        self.client.force_login(self.trainer)
        self.scan()
        self.client.force_login(self.coordinator)
        self.assertEqual(self.client.post("/audit/checkpoint/", {"receipt": receipt}).status_code, 200)
