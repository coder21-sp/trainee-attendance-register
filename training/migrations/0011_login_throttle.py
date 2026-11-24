from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("training", "0010_coordinator_permission")]

    operations = [
        migrations.CreateModel(
            name="LoginAttemptBucket",
            fields=[
                ("key", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("expires_at", models.DateTimeField(db_index=True)),
            ],
        ),
    ]
