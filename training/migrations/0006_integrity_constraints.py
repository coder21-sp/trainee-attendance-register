from django.db import migrations, models
from django.db.models import F, Q


def preflight(apps, schema_editor):
    alias = schema_editor.connection.alias
    Batch = apps.get_model("training", "Batch")
    Approval = apps.get_model("training", "Approval")
    Attendance = apps.get_model("training", "Attendance")
    checks = {
        "batch thresholds": Batch.objects.using(alias).exclude(minimum_percent__range=(0, 100)),
        "approval thresholds": Approval.objects.using(alias).exclude(threshold__range=(0, 100)),
        "approval totals": Approval.objects.using(alias).filter(Q(total__lte=0) | Q(attended__gt=F("total"))),
        "cross-batch attendance": Attendance.objects.using(alias).exclude(trainee__batch_id=F("session__batch_id")),
    }
    invalid = []
    for label, queryset in checks.items():
        ids = list(queryset.values_list("pk", flat=True)[:20])
        if ids:
            invalid.append(f"{label}: {ids}")
    if invalid:
        raise RuntimeError("Resolve invalid legacy records before migrating: " + "; ".join(invalid))


TRIGGERS = {
    "attendance_same_batch_insert": """
        BEFORE INSERT ON training_attendance
        WHEN (SELECT batch_id FROM training_trainee WHERE id = NEW.trainee_id)
             <> (SELECT batch_id FROM training_session WHERE id = NEW.session_id)
    """,
    "attendance_same_batch_update": """
        BEFORE UPDATE OF trainee_id, session_id ON training_attendance
        WHEN (SELECT batch_id FROM training_trainee WHERE id = NEW.trainee_id)
             <> (SELECT batch_id FROM training_session WHERE id = NEW.session_id)
    """,
    "trainee_preserve_attendance_batch": """
        BEFORE UPDATE OF batch_id ON training_trainee
        WHEN EXISTS (SELECT 1 FROM training_attendance a
            JOIN training_session s ON s.id = a.session_id
            WHERE a.trainee_id = OLD.id AND s.batch_id <> NEW.batch_id)
    """,
    "session_preserve_attendance_batch": """
        BEFORE UPDATE OF batch_id ON training_session
        WHEN EXISTS (SELECT 1 FROM training_attendance a
            JOIN training_trainee t ON t.id = a.trainee_id
            WHERE a.session_id = OLD.id AND t.batch_id <> NEW.batch_id)
    """,
}


def install_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "sqlite":
        raise RuntimeError("This migration requires SQLite integrity triggers")
    for name, clause in TRIGGERS.items():
        schema_editor.execute(
            f"CREATE TRIGGER {name} {clause} BEGIN "
            "SELECT RAISE(ABORT, 'Attendance batch mismatch'); END;"
        )


def remove_triggers(apps, schema_editor):
    for name in TRIGGERS:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {name}")


class Migration(migrations.Migration):
    dependencies = [("training", "0005_lock_audit")]
    operations = [
        migrations.RunPython(preflight, migrations.RunPython.noop),
        migrations.AddConstraint(model_name="batch", constraint=models.CheckConstraint(
            condition=Q(minimum_percent__gte=0, minimum_percent__lte=100), name="batch_threshold_range")),
        migrations.AddConstraint(model_name="approval", constraint=models.CheckConstraint(
            condition=Q(threshold__gte=0, threshold__lte=100), name="approval_threshold_range")),
        migrations.AddConstraint(model_name="approval", constraint=models.CheckConstraint(
            condition=Q(total__gt=0), name="approval_positive_total")),
        migrations.AddConstraint(model_name="approval", constraint=models.CheckConstraint(
            condition=Q(attended__lte=F("total")), name="approval_attended_within_total")),
        migrations.RunPython(install_triggers, remove_triggers),
    ]
