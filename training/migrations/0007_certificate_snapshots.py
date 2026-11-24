from django.db import migrations, models


def backfill(apps, schema_editor):
    Approval = apps.get_model("training", "Approval")
    alias = schema_editor.connection.alias
    for approval in Approval.objects.using(alias).select_related("trainee__batch", "reviewer").iterator():
        Approval.objects.using(alias).filter(pk=approval.pk).update(
            trainee_name=approval.trainee.name,
            trainee_code=approval.trainee.code,
            batch_name=approval.trainee.batch.name,
            reviewer_name=approval.reviewer.username,
            approval_method="legacy_unknown",
            snapshot_origin="reconstructed",
        )


class Migration(migrations.Migration):
    dependencies = [("training", "0006_integrity_constraints")]
    operations = [
        *[
            migrations.AddField(
                model_name="approval", name=name,
                field=models.CharField(max_length=length, default=default, editable=False),
            )
            for name, length, default in [
                ("trainee_name", 100, ""),
                ("trainee_code", 50, ""),
                ("batch_name", 100, ""),
                ("reviewer_name", 150, ""),
                ("approval_method", 16, "legacy_unknown"),
                ("snapshot_origin", 16, "reconstructed"),
            ]
        ],
        migrations.RunPython(backfill, migrations.RunPython.noop),
        *[
            migrations.RunSQL(
                f"CREATE TRIGGER approval_no_{op.lower()} BEFORE {op} ON training_approval "
                "BEGIN SELECT RAISE(ABORT, 'Approved certificates are immutable'); END;",
                reverse_sql=f"DROP TRIGGER approval_no_{op.lower()};",
            )
            for op in ("UPDATE", "DELETE")
        ],
        migrations.RunSQL(
            """CREATE TRIGGER approval_no_replace BEFORE INSERT ON training_approval
            WHEN EXISTS (SELECT 1 FROM training_approval WHERE id=NEW.id OR trainee_id=NEW.trainee_id)
            BEGIN SELECT RAISE(ABORT, 'Approved certificates are immutable'); END;""",
            reverse_sql="DROP TRIGGER approval_no_replace;",
        ),
    ]
