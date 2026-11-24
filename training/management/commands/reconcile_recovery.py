"""Verify a quarantined SQLite register against an independently held snapshot."""
from contextlib import closing
import hashlib
from itertools import zip_longest
import json
from pathlib import Path
import sqlite3

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from training.models import AuditEntry
from training.recovery import RECONCILED, marker_digest, pending_restore, valid_marker
from .restore_with_audit import COLUMNS, TABLE


OPERATIONAL_TABLES = (
    "training_batch", "training_trainee", "training_session", "training_attendance",
    "training_approval", "training_correction", "auth_user", "auth_user_groups",
    "auth_user_user_permissions", "auth_group", "auth_group_permissions", "auth_permission",
    "django_content_type", "django_migrations",
)


def compare_evidence(candidate, evidence, marker):
    digest = hashlib.sha256(b"training.recovery.evidence.v1\n")
    for db in (candidate, evidence):
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise CommandError("Database failed its integrity check.")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise CommandError("Database contains invalid foreign keys.")
    for table in (*OPERATIONAL_TABLES, TABLE):
        digest.update(table.encode() + b"\n")
        if table == TABLE:
            expected = evidence.execute(f"SELECT {COLUMNS} FROM {TABLE} ORDER BY id")
            actual = candidate.execute(
                f"SELECT {COLUMNS} FROM {TABLE} WHERE id < ? ORDER BY id", (marker.pk,),
            )
        else:
            schema = candidate.execute(f'PRAGMA table_info("{table}")').fetchall()
            if not schema or schema != evidence.execute(f'PRAGMA table_info("{table}")').fetchall():
                raise CommandError(f"Database schema differs for {table}.")
            fields = ", ".join(f'"{column[1]}"' for column in schema if column[1] != "last_login")
            query = f'SELECT {fields} FROM "{table}" ORDER BY id'
            expected, actual = evidence.execute(query), candidate.execute(query)
        for left, right in zip_longest(expected, actual):
            if left != right:
                if table == TABLE:
                    raise CommandError("Evidence audit history differs from the retained history.")
                raise CommandError(f"Operational evidence differs for {table}.")
            digest.update(json.dumps(left, ensure_ascii=False, separators=(",", ":"), default=str).encode() + b"\n")
    return digest.hexdigest()


class Command(BaseCommand):
    help = "Verify a restored SQLite register against a trusted, independently held snapshot."

    def add_arguments(self, parser):
        parser.add_argument("evidence")
        parser.add_argument("--actor", required=True)
        parser.add_argument("--note", required=True)

    @transaction.atomic
    def handle(self, *args, **opts):
        note = opts["note"].strip()
        if not note or len(note) > 240:
            raise CommandError("Provide a review note of 1 to 240 characters.")
        actor = get_user_model().objects.filter(
            username=opts["actor"], is_active=True, is_superuser=True,
        ).first()
        if actor is None:
            raise CommandError("An active coordinator is required.")
        marker = pending_restore()
        if marker is None:
            raise CommandError("No restore awaits review.")
        if not valid_marker(marker):
            raise CommandError("Recovery marker is malformed.")

        evidence_path = Path(opts["evidence"])
        candidate_path = Path(connection.settings_dict["NAME"])
        try:
            if candidate_path.is_file() and evidence_path.samefile(candidate_path):
                raise CommandError("Select evidence independent of the restored database.")
            with closing(sqlite3.connect(
                evidence_path.resolve().as_uri() + "?mode=ro", uri=True,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            )) as evidence:
                evidence.execute("BEGIN")
                digest = compare_evidence(connection.connection, evidence, marker)
        except (OSError, sqlite3.Error) as exc:
            raise CommandError("Could not read or validate SQLite evidence.") from exc
        payload = {"version": 1, "marker_id": marker.pk, "marker_digest": marker_digest(marker),
                   "evidence_digest": digest, "actor_id": actor.pk}
        AuditEntry.objects.create(
            trainee_name="(Entire register)", actor=f"{actor.username} (Coordinator)",
            context="Recovery reconciled\n" + json.dumps(payload, separators=(",", ":")),
            reason=RECONCILED, note=note, seed_key=f"recovery-reconciled:{marker.pk}",
        )
        self.stdout.write(f"Recovery #{marker.pk} reconciled. Evidence SHA-256 {digest}.")
