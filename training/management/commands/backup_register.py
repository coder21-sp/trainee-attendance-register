"""Create an independent SQLite snapshot using the online backup API."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from .restore_with_audit import readonly


REGISTER_TABLES = {
    "django_migrations", "training_batch", "training_trainee", "training_session",
    "training_attendance", "training_approval", "training_auditentry",
}


class Command(BaseCommand):
    help = "Back up a SQLite register to a new file without replacing either database."

    def add_arguments(self, parser):
        parser.add_argument("output")
        parser.add_argument("--source", default=settings.DATABASES["default"]["NAME"])

    def handle(self, *args, **options):
        output = Path(options["output"]).resolve()
        if output.exists():
            raise CommandError("Output already exists.")
        try:
            with TemporaryDirectory(dir=output.parent) as directory:
                staged = Path(directory) / "backup.sqlite3"
                with closing(readonly(options["source"])) as source, closing(sqlite3.connect(staged)) as copy:
                    source.backup(copy)
                    tables = {row[0] for row in copy.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
                    if not REGISTER_TABLES <= tables:
                        raise CommandError("Source is missing the register schema.")
                    if copy.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                        raise CommandError("Backup failed its SQLite integrity check.")
                    if copy.execute("PRAGMA foreign_key_check").fetchone():
                        raise CommandError("Backup contains invalid foreign keys.")
                os.chmod(staged, 0o600)
                os.link(staged, output)
        except FileExistsError as exc:
            raise CommandError("Output already exists.") from exc
        except (OSError, sqlite3.Error) as exc:
            raise CommandError("Could not create the SQLite backup.") from exc
        self.stdout.write("SQLite backup created and verified.")
