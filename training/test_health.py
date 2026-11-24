from unittest.mock import patch

from django.db import connection, OperationalError
from django.test import TestCase

from .models import AuditEntry


class HealthTests(TestCase):
    def test_liveness_stays_healthy_during_quarantine(self):
        AuditEntry.objects.create(reason="Recovery required")
        response = self.client.get("/health/live/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_readiness_tracks_quarantine(self):
        response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})
        self.assertIn("no-store", response.headers["Cache-Control"])
        AuditEntry.objects.create(reason="Recovery required")
        response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})

    def test_readiness_omits_database_error_details(self):
        with (
            patch("training.recovery.connection.cursor", side_effect=OperationalError("private path")),
            self.assertLogs("training.health", level="WARNING") as logs,
        ):
            response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})
        self.assertNotIn("private path", "\n".join(logs.output))

    def test_readiness_requires_the_login_schema(self):
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE training_loginattemptbucket")
        with self.assertLogs("training.health", level="WARNING"):
            response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 503)
