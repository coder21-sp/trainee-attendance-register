from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase
from django.core.management.base import CommandError
from training.management.commands.restore_with_audit import snapshot


class RestoreTest(TestCase):
    def test_combined_history_and_conflict(self):
        with TemporaryDirectory() as tmp:
            old, live, output = [Path(tmp)/name for name in ("old","live","recovered")]
            with closing(sqlite3.connect(old)) as db, closing(sqlite3.connect(live)) as current:
                db.execute("CREATE TABLE training_auditentry(id INTEGER PRIMARY KEY,timestamp,trainee_name,context,actor,reason,note,seed_key)")
                db.execute("INSERT INTO training_auditentry(id,note) VALUES (1,'Monday')")
                db.commit()
                db.backup(current)
                current.execute("INSERT INTO training_auditentry(id,note) VALUES (2,'Tuesday')")
                current.commit()
                self.assertEqual(snapshot(old,live,output),1)
                with closing(sqlite3.connect(output)) as restored:
                    self.assertEqual(restored.execute("SELECT id,note FROM training_auditentry WHERE id <= 2 ORDER BY id").fetchall(),[(1,"Monday"),(2,"Tuesday")])
                with self.assertRaises(FileExistsError):
                    snapshot(old,live,output)
                current.execute("UPDATE training_auditentry SET note='changed' WHERE id=1")
                current.commit()
                with self.assertRaises(CommandError):
                    snapshot(old,live,Path(tmp)/"conflict")
                self.assertFalse((Path(tmp)/"conflict").exists())
