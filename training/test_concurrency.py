import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .models import Attendance, AuditEntry, Batch, Session, Trainee


class RegisterConcurrencyTests(TransactionTestCase):
    def setUp(self):
        users = get_user_model().objects
        trainer = users.create(username="race-trainer")
        coordinator = users.create(username="race-coordinator", is_staff=True, is_superuser=True)
        batch = Batch.objects.create(name="Concurrency batch")
        self.trainee = Trainee.objects.create(batch=batch, name="Concurrency trainee", code="RACE-1")
        self.session = Session.objects.create(
            batch=batch, title="Concurrency session", date=timezone.localdate(), trainer=trainer,
        )
        self.trainer_clients = self.signed_in_clients(trainer)
        self.coordinator_clients = self.signed_in_clients(coordinator)
        self.mark = (
            reverse("mark-api", args=[self.session.pk]),
            {"source": "scan", "code": str(self.trainee.badge)},
        )
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "concurrency.sqlite3"

    @staticmethod
    def signed_in_clients(user):
        clients = (Client(), Client())
        for client in clients:
            client.force_login(user)
        return clients

    def race(self, *operations):
        # Clone the migrated test database, including signed-in sessions, so
        # worker threads exercise file locks against separate connections.
        with closing(sqlite3.connect(self.database)) as target:
            connection.connection.backup(target)
        start = Barrier(len(operations))

        def run(operation):
            try:
                start.wait(timeout=10)
                return operation()
            finally:
                connections["default"].close()

        database_settings = connections.databases["default"]
        with patch.dict(database_settings, NAME=str(self.database)):
            with ThreadPoolExecutor(max_workers=len(operations)) as pool:
                futures = [pool.submit(run, operation) for operation in operations]
                return [future.result(timeout=30) for future in futures]

    @staticmethod
    def post(client, request):
        path, data = request
        return client.post(path, data, HTTP_ACCEPT="application/json").status_code

    def race_posts(self, clients, *requests):
        return self.race(*(
            partial(self.post, client, request)
            for client, request in zip(clients, requests, strict=True)
        ))

    def rows(self, query):
        with closing(sqlite3.connect(self.database)) as database:
            return database.execute(query).fetchall()

    def audit_actions(self):
        return [
            json.loads(context.split("\n", 1)[1])["action"]
            for (context,) in self.rows("SELECT context FROM training_auditentry ORDER BY id")
        ]

    def assert_attendance(self, expected):
        self.assertEqual(self.rows("SELECT session_id, trainee_id FROM training_attendance"), expected)

    def close_attended_register(self):
        Attendance.objects.create(session=self.session, trainee=self.trainee)
        self.session.closed = True
        self.session.save(update_fields=["closed"])

    def test_simultaneous_duplicate_qr_scans_record_one_mark(self):
        self.assertEqual(self.race_posts(self.trainer_clients, self.mark, self.mark), [200, 200])
        self.assert_attendance([(self.session.pk, self.trainee.pk)])
        self.assertEqual(self.audit_actions(), ["attendance_marked"])

    def test_simultaneous_approvals_issue_one_certificate(self):
        self.close_attended_register()
        approve = (reverse("approve", args=[self.trainee.pk]), {})

        self.assertEqual(self.race_posts(self.coordinator_clients, approve, approve), [302, 302])
        self.assertEqual(
            self.rows("SELECT trainee_id, attended, total, snapshot_origin FROM training_approval"),
            [(self.trainee.pk, 1, 1, "original")],
        )
        self.assertEqual(self.audit_actions(), ["certificate_approved"])

    def test_close_and_scan_observe_a_consistent_register(self):
        close = (reverse("register", args=[self.session.pk]), {"action": "close"})
        close_status, scan_status = self.race_posts(self.trainer_clients, close, self.mark)
        self.assertEqual(close_status, 200)
        self.assertEqual(self.rows("SELECT closed FROM training_session"), [(1,)])
        self.assertIn(scan_status, (200, 400))
        if scan_status == 200:
            self.assert_attendance([(self.session.pk, self.trainee.pk)])
            self.assertEqual(self.audit_actions(), ["attendance_marked", "register_closed"])
        else:
            self.assert_attendance([])
            self.assertEqual(self.audit_actions(), ["register_closed"])

    def test_correction_and_approval_preserve_certificate_evidence(self):
        self.close_attended_register()
        correct = (
            reverse("register", args=[self.session.pk]),
            {"action": "correct", "code": self.trainee.code, "status": "absent",
             "reason": "Roster Correction"},
        )
        approve = (reverse("approve", args=[self.trainee.pk]), {})
        clients = (self.trainer_clients[0], self.coordinator_clients[0])

        self.assertEqual(self.race_posts(clients, correct, approve), [302, 302])
        approvals = self.rows("SELECT trainee_id, attended, total FROM training_approval")
        if approvals:
            self.assertEqual(approvals, [(self.trainee.pk, 1, 1)])
            self.assert_attendance([(self.session.pk, self.trainee.pk)])
            self.assertEqual(self.audit_actions(), ["certificate_approved"])
        else:
            self.assert_attendance([])
            self.assertEqual(self.audit_actions(), ["attendance_corrected"])

    def test_batch_threshold_change_and_approval_preserve_certificate_evidence(self):
        self.close_attended_register()
        batch = self.trainee.batch
        batch.minimum_percent = 50
        batch.save(update_fields=["minimum_percent"])
        Session.objects.create(
            batch=batch, title="Second session", date=self.session.date,
            trainer_id=self.session.trainer_id, closed=True,
        )
        change_threshold = (
            reverse("admin:training_batch_change", args=[batch.pk]),
            {"name": batch.name, "minimum_percent": 75, "_save": "Save"},
        )
        approve = (reverse("approve", args=[self.trainee.pk]), {})

        change_status, approval_status = self.race_posts(self.coordinator_clients, change_threshold, approve)
        self.assertEqual(approval_status, 302)
        approvals = self.rows("SELECT trainee_id, attended, total, threshold FROM training_approval")
        if approvals:
            self.assertEqual(change_status, 200)
            self.assertEqual(approvals, [(self.trainee.pk, 1, 2, 50)])
            self.assertEqual(self.rows("SELECT minimum_percent FROM training_batch"), [(50,)])
            self.assertEqual(self.audit_actions(), ["certificate_approved"])
        else:
            self.assertEqual(change_status, 302)
            self.assertEqual(self.rows("SELECT minimum_percent FROM training_batch"), [(75,)])
            self.assertEqual(self.audit_actions(), [])

    def test_recovery_marker_and_scan_serialize_quarantine(self):
        def quarantine():
            payload = {"version": 1, "action": "recovery_required", "source": "restore",
                       "retained_event_count": 0, "backup_reference": "backup.sqlite3"}
            AuditEntry.objects.create(
                trainee_name="(Entire register)", actor="Restore command",
                reason="Recovery required", note="Independent reconciliation required",
                context="Recovery required\n" + json.dumps(payload),
            )

        scan = partial(self.post, self.trainer_clients[0], self.mark)
        _, scan_status = self.race(quarantine, scan)
        self.assertIn(scan_status, (200, 409))
        if scan_status == 200:
            self.assert_attendance([(self.session.pk, self.trainee.pk)])
            self.assertEqual(self.audit_actions(), ["attendance_marked", "recovery_required"])
        else:
            self.assert_attendance([])
            self.assertEqual(self.audit_actions(), ["recovery_required"])
