from django.db import migrations


def import_corrections(apps, schema_editor):
    audit = apps.get_model("training", "AuditEntry")
    corrections = apps.get_model("training", "Correction")
    for c in corrections.objects.select_related("trainee","session__batch","reviewer").iterator():
        action = "Mark added" if c.present else "Mark removed"
        role = "Coordinator" if c.reviewer.is_superuser else "Trainer"
        audit.objects.create(timestamp=c.recorded_at, trainee_name=f"{c.trainee.name} ({c.trainee.code})",
            context=f"{c.session.batch.name} · {c.session.date} · {c.session.title} · {action}",
            actor=f"{c.reviewer.username} ({role})", reason="Historical correction", note=c.reason)


class Migration(migrations.Migration):
    dependencies = [("training", "0004_auditentry")]
    operations = [
        migrations.RunPython(import_corrections),
        *[migrations.RunSQL(
            f"CREATE TRIGGER audit_no_{op} BEFORE {op} ON training_auditentry BEGIN SELECT RAISE(ABORT, 'Audit entries are immutable'); END;"
        ) for op in ("UPDATE", "DELETE")],
        migrations.RunSQL("""CREATE TRIGGER audit_no_replace BEFORE INSERT ON training_auditentry
            WHEN EXISTS (SELECT 1 FROM training_auditentry WHERE id=NEW.id OR seed_key=NEW.seed_key)
            BEGIN SELECT RAISE(ABORT, 'Audit entries are immutable'); END;"""),
    ]
