from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase


class BackupTests(TestCase):
    def test_backup_rejects_an_unrelated_sqlite_file(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite3"
            output = Path(directory) / "backup.sqlite3"
            with closing(sqlite3.connect(source)) as db:
                db.execute("CREATE TABLE unrelated (name TEXT)")
            with self.assertRaisesMessage(CommandError, "Source is missing the register schema"):
                call_command("backup_register", str(output), source=str(source))
            self.assertFalse(output.exists())

    def test_backup_captures_committed_wal_data_without_replacing_files(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite3"
            output = Path(directory) / "backup.sqlite3"
            with closing(sqlite3.connect(source)) as db:
                db.execute("PRAGMA journal_mode = WAL")
                db.executescript("\n".join(connection.connection.iterdump()))
                db.execute("INSERT INTO training_batch (name, minimum_percent) VALUES ('synthetic', 75)")
                db.commit()

                call_command("backup_register", str(output), source=str(source))

                with closing(sqlite3.connect(output)) as backup:
                    self.assertEqual(backup.execute("SELECT name FROM training_batch").fetchall(), [("synthetic",)])
                self.assertEqual(db.execute("SELECT name FROM training_batch").fetchall(), [("synthetic",)])
                before = output.read_bytes()
                with self.assertRaisesMessage(CommandError, "Output already exists"):
                    call_command("backup_register", str(output), source=str(source))
                self.assertEqual(output.read_bytes(), before)
