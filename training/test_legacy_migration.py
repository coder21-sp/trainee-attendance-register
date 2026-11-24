import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


class LegacyRegisterMigrationTests(TestCase):
    def test_upgrade_preserves_and_locks_legacy_records(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            result = subprocess.run(
                [sys.executable, "-m", "training.test_legacy_migration", str(path)],
                cwd=Path(__file__).resolve().parents[1],
                env={
                    **os.environ,
                    "APP_ENV": "development",
                    "DJANGO_SETTINGS_MODULE": "config.settings",
                    "SECRET_KEY": "legacy-migration-test-key",
                },
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            with closing(sqlite3.connect(path)) as database:
                self.assertEqual(
                    database.execute(
                        "SELECT id, trainee_name, trainee_code, batch_name, reviewer_name, "
                        "approval_method, snapshot_origin, attended, total, threshold "
                        "FROM training_approval"
                    ).fetchall(),
                    [(1, "Legacy trainee", "LEG-1", "Legacy batch", "legacy-reviewer",
                      "legacy_unknown", "reconstructed", 1, 1, 75)],
                )
                self.assertEqual(
                    database.execute(
                        "SELECT trainee_name, actor, reason, note FROM training_auditentry ORDER BY id"
                    ).fetchall(),
                    [
                        ("Legacy trainee", "Original operator", "Original audit", "Retained note"),
                        ("Legacy trainee (LEG-1)", "legacy-reviewer (Coordinator)",
                         "Historical correction", "Legacy marked present"),
                    ],
                )
                with self.assertRaisesRegex(sqlite3.IntegrityError, "Audit entries are immutable"):
                    database.execute("UPDATE training_auditentry SET note = 'Edited' WHERE id = 1")
                with self.assertRaisesRegex(sqlite3.IntegrityError, "Approved certificates are immutable"):
                    database.execute("DELETE FROM training_approval WHERE id = 1")
                database.execute(
                    "INSERT INTO training_auditentry "
                    "(timestamp, trainee_name, context, actor, reason, note) "
                    "VALUES (CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)",
                    ("(Entire register)", "Legacy recovery marker", "Restore command",
                     "Recovery required", "Reconciliation required"),
                )
                with self.assertRaisesRegex(sqlite3.IntegrityError, "Recovery reconciliation required"):
                    database.execute("UPDATE training_batch SET name = 'Edited' WHERE id = 1")
                self.assertEqual(database.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
                self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])


def migrate_legacy_fixture(path):
    import django

    # Refuse existing databases even when invoked outside the test runner.
    path.touch(exist_ok=False)
    os.environ["DATABASE_PATH"] = str(path.resolve())
    django.setup()
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    # The historical correction migration uses the default alias. A subprocess
    # gives it a separate default database without changing the test runner's.
    targets = [("training", "0004_auditentry")]
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    apps = executor.loader.project_state(targets).apps

    reviewer = apps.get_model("auth", "User").objects.create(
        username="legacy-reviewer", is_superuser=True,
    )
    batch = apps.get_model("training", "Batch").objects.create(name="Legacy batch")
    trainee = apps.get_model("training", "Trainee").objects.create(
        name="Legacy trainee", code="LEG-1", batch=batch,
    )
    session = apps.get_model("training", "Session").objects.create(
        batch=batch, trainer=reviewer, title="Legacy session", date=date(2024, 8, 1), closed=True,
    )
    apps.get_model("training", "Attendance").objects.create(session=session, trainee=trainee)
    apps.get_model("training", "Approval").objects.create(
        trainee=trainee, reviewer=reviewer, attended=1, total=1, threshold=75,
    )
    apps.get_model("training", "Correction").objects.create(
        session=session, trainee=trainee, reviewer=reviewer, present=True, reason="Legacy marked present",
    )
    apps.get_model("training", "AuditEntry").objects.create(
        trainee_name=trainee.name, actor="Original operator", reason="Original audit",
        context="Legacy context", note="Retained note",
    )

    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    connection.close()


if __name__ == "__main__":
    migrate_legacy_fixture(Path(sys.argv[1]))
