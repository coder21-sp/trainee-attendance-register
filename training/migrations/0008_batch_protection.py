from django.db import migrations


def locked(batch):
    return (
        "EXISTS (SELECT 1 FROM training_approval a "
        "JOIN training_trainee t ON t.id = a.trainee_id "
        f"WHERE t.batch_id = {batch})"
    )


def approved(trainee):
    return f"EXISTS (SELECT 1 FROM training_approval WHERE trainee_id = {trainee})"


TRIGGERS = {
    "locked_batch_threshold": (
        "BEFORE UPDATE OF minimum_percent ON training_batch",
        f"OLD.minimum_percent IS NOT NEW.minimum_percent AND {locked('OLD.id')}",
    ),
    "locked_session_insert": (
        "BEFORE INSERT ON training_session", locked("NEW.batch_id"),
    ),
    "locked_session_delete": (
        "BEFORE DELETE ON training_session", locked("OLD.batch_id"),
    ),
    "locked_session_update": (
        "BEFORE UPDATE ON training_session",
        "(OLD.batch_id IS NOT NEW.batch_id OR OLD.title IS NOT NEW.title "
        "OR OLD.date IS NOT NEW.date OR OLD.closed IS NOT NEW.closed "
        "OR OLD.trainer_id IS NOT NEW.trainer_id OR OLD.id IS NOT NEW.id) "
        f"AND ({locked('OLD.batch_id')} OR {locked('NEW.batch_id')})",
    ),
    "locked_trainee_insert": (
        "BEFORE INSERT ON training_trainee", locked("NEW.batch_id"),
    ),
    "locked_trainee_delete": (
        "BEFORE DELETE ON training_trainee", locked("OLD.batch_id"),
    ),
    "locked_trainee_transfer": (
        "BEFORE UPDATE OF batch_id ON training_trainee",
        f"OLD.batch_id IS NOT NEW.batch_id AND ({locked('OLD.batch_id')} OR {locked('NEW.batch_id')})",
    ),
    "approved_mark_insert": (
        "BEFORE INSERT ON training_attendance", approved("NEW.trainee_id"),
    ),
    "approved_mark_delete": (
        "BEFORE DELETE ON training_attendance", approved("OLD.trainee_id"),
    ),
    "approved_mark_update": (
        "BEFORE UPDATE ON training_attendance",
        f"{approved('OLD.trainee_id')} OR {approved('NEW.trainee_id')}",
    ),
    "locked_session_no_replace": (
        "BEFORE INSERT ON training_session",
        "EXISTS (SELECT 1 FROM training_session s WHERE s.id = NEW.id "
        f"AND {locked('s.batch_id')})",
    ),
    "locked_trainee_no_replace": (
        "BEFORE INSERT ON training_trainee",
        "EXISTS (SELECT 1 FROM training_trainee t WHERE "
        "(t.id = NEW.id OR t.code = NEW.code OR t.badge = NEW.badge OR t.account_id = NEW.account_id) "
        f"AND {locked('t.batch_id')})",
    ),
    "approved_mark_no_replace": (
        "BEFORE INSERT ON training_attendance",
        "EXISTS (SELECT 1 FROM training_attendance m WHERE m.id = NEW.id "
        f"AND {approved('m.trainee_id')})",
    ),
    "locked_batch_no_replace": (
        "BEFORE INSERT ON training_batch",
        "EXISTS (SELECT 1 FROM training_batch b WHERE (b.id = NEW.id OR b.name = NEW.name) "
        f"AND {locked('b.id')})",
    ),
}


class Migration(migrations.Migration):
    dependencies = [("training", "0007_certificate_snapshots")]
    operations = [
        migrations.RunSQL(
            f"CREATE TRIGGER {name} {event} WHEN {condition} "
            "BEGIN SELECT RAISE(ABORT, 'Approved batch or attendance is locked'); END;",
            reverse_sql=f"DROP TRIGGER {name};",
        )
        for name, (event, condition) in TRIGGERS.items()
    ]
