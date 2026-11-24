"""Prepare a restored SQLite database while preserving the current audit history."""
from contextlib import closing
import os
import json
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

TABLE = "training_auditentry"
COLUMNS = "id,timestamp,trainee_name,context,actor,reason,note,seed_key"


def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def snapshot(backup, current, output):
    output = Path(output).resolve()
    # Publish the completed file atomically and exclusively on the same filesystem.
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        stage = Path(directory) / "restore.sqlite3"
        with closing(readonly(backup)) as old, closing(readonly(current)) as live, closing(sqlite3.connect(stage)) as dest:
            old.backup(dest)
            live.execute("BEGIN")
            last = dest.execute(f"SELECT MAX(id) FROM {TABLE}").fetchone()[0] or 0
            query = f"SELECT {COLUMNS} FROM {TABLE}"
            earlier = dest.execute(query + " ORDER BY id")
            prefix = live.execute(query + " WHERE id <= ? ORDER BY id", (last,))
            from itertools import zip_longest
            if any(a != b for a,b in zip_longest(earlier, prefix)):
                raise CommandError("Audit histories diverge. Keep both source files for review.")
            with dest:
                appended = dest.executemany(
                    f"INSERT INTO {TABLE} ({COLUMNS}) VALUES (?,?,?,?,?,?,?,?)",
                    live.execute(query + " WHERE id > ? ORDER BY id", (last,)),
                ).rowcount
                # Every restored copy requires independent review, even when no
                # later audit rows exist: legacy operational changes may be unaudited.
                payload = {"version": 1, "action": "recovery_required", "source": "restore",
                           "retained_event_count": appended, "backup_reference": Path(backup).name}
                dest.execute(
                    f"INSERT INTO {TABLE} (timestamp,trainee_name,context,actor,reason,note,seed_key) VALUES (?,?,?,?,?,?,?)",
                    (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" "),
                     "(Entire register)", "Recovery required\n" + json.dumps(payload, separators=(",", ":")),
                     "Restore command", "Recovery required", "Independent reconciliation required", None),
                )
            if dest.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise CommandError("Restored database failed its integrity check.")
        os.chmod(stage, 0o600)
        os.link(stage, output)
    return appended


class Command(BaseCommand):
    help = "Copy a backup into a new database and carry forward all later audit entries."

    def add_arguments(self, parser):
        parser.add_argument("backup")
        parser.add_argument("output")
        parser.add_argument("--current", default=settings.DATABASES["default"]["NAME"])

    def handle(self, *args, **opts):
        try:
            count = snapshot(opts["backup"], opts["current"], opts["output"])
        except (sqlite3.Error, OSError) as exc:
            raise CommandError(f"Could not prepare restore: {exc}") from exc
        self.stdout.write(f"Restore ready: {opts['output']} ({count} later audit entries retained). Reconciliation required before use.")
