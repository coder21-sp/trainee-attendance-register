"""Regression tests for fail-closed recovery, using real SQLite snapshots."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .management.commands.restore_with_audit import snapshot
from .models import Approval, Attendance, AuditEntry, Batch, Session, Trainee


def recovery_payload():
    return {"version": 1, "action": "recovery_required", "source": "restore",
            "retained_event_count": 1, "backup_reference": "old.sqlite3"}


class RecoverySnapshotTests(TestCase):
    def test_restore_persists_recovery_warning_without_changing_sources(self):
        with TemporaryDirectory() as tmp:
            old, live, output = [Path(tmp) / name for name in
                                 ("old.sqlite3", "live.sqlite3", "restored.sqlite3")]
            with closing(sqlite3.connect(old)) as db, closing(sqlite3.connect(live)) as current:
                db.execute("CREATE TABLE training_auditentry(id INTEGER PRIMARY KEY,timestamp,trainee_name,context,actor,reason,note,seed_key)")
                db.execute("CREATE TABLE training_attendance(id INTEGER PRIMARY KEY)")
                db.execute("INSERT INTO training_auditentry(id,note) VALUES (1,'Monday')")
                db.commit()
                db.backup(current)
                current.execute("INSERT INTO training_auditentry(id,note) VALUES (2,'Tuesday')")
                current.execute("INSERT INTO training_attendance(id) VALUES (1)")
                current.commit()
                self.assertEqual(snapshot(old, live, output), 1)
                with closing(sqlite3.connect(output)) as restored:
                    self.assertEqual(restored.execute("SELECT note FROM training_auditentry WHERE id <= 2 ORDER BY id").fetchall(),
                                     [("Monday",), ("Tuesday",)])
                    self.assertEqual(restored.execute("SELECT COUNT(*) FROM training_attendance").fetchone()[0], 0)
                    markers = restored.execute(
                        "SELECT context FROM training_auditentry WHERE reason = ?",
                        ("Recovery required",)).fetchall()
                    self.assertEqual(len(markers), 1)
                    payload = json.loads(markers[0][0].split("\n", 1)[1])
                    self.assertEqual(payload["action"], "recovery_required")
                    self.assertEqual(payload["retained_event_count"], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM training_auditentry").fetchone()[0], 1)
                self.assertEqual(current.execute("SELECT COUNT(*) FROM training_auditentry").fetchone()[0], 2)
                self.assertEqual(current.execute("SELECT COUNT(*) FROM training_attendance").fetchone()[0], 1)


class RecoveryLockTests(TestCase):
    def setUp(self):
        self.coordinator = get_user_model().objects.create(
            username="recovery-coordinator", is_superuser=True, is_staff=True)
        self.trainer = get_user_model().objects.create(username="recovery-trainer")
        self.batch = Batch.objects.create(name="Recovery batch")
        self.trainee = Trainee.objects.create(batch=self.batch, name="Recovery trainee", code="REC-1")
        self.session = Session.objects.create(batch=self.batch, title="Workshop",
                                              trainer=self.trainer, date=timezone.localdate())
        self.route = f"/sessions/{self.session.pk}/"
        self.client.force_login(self.coordinator)
        AuditEntry.objects.create(
            trainee_name="(Entire register)", actor="Restore command",
            reason="Recovery required", note="Independent reconciliation required",
            context="Recovery required\n" + json.dumps(recovery_payload(), separators=(",", ":")))

    def test_qr_attendance_blocked(self):
        self.client.force_login(self.trainer)
        response = self.client.post(self.route, {"source": "scan", "code": str(self.trainee.badge)})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Attendance.objects.exists())

    def test_manual_attendance_blocked(self):
        response = self.client.post(self.route, {"code": self.trainee.code, "reason": "Network Error"})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Attendance.objects.exists())

    def test_correction_blocked(self):
        response = self.client.post(self.route, {"action": "correct", "code": self.trainee.code,
                                                 "status": "present", "reason": "Roster Correction"})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Attendance.objects.exists())

    def test_register_closure_blocked(self):
        response = self.client.post(self.route, {"action": "close"})
        self.assertEqual(response.status_code, 409)
        self.session.refresh_from_db()
        self.assertFalse(self.session.closed)

    def test_approval_blocked_even_when_eligible(self):
        Attendance.objects.create(trainee=self.trainee, session=self.session)
        Session.objects.filter(pk=self.session.pk).update(closed=True)
        response = self.client.post(f"/approve/{self.trainee.pk}/")
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Approval.objects.exists())

    def test_review_displays_recovery_warning(self):
        response = self.client.get(f"/review/{self.batch.pk}/")
        self.assertContains(response, "Reconciliation required", status_code=200)

    def test_admin_cannot_add_batch_during_recovery(self):
        response = self.client.post(reverse("admin:training_batch_add"),
                                    {"name": "Unsafe batch", "minimum_percent": 75, "_save": "Save"})
        self.assertIn(response.status_code, (403, 409))
        self.assertFalse(Batch.objects.filter(name="Unsafe batch").exists())

    def test_audit_history_remains_readable(self):
        self.assertContains(self.client.get("/audit/"), "Recovery required")

    def test_checkpoint_reports_recovery_status(self):
        response = self.client.post("/audit/checkpoint/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("recovery_required", False))
