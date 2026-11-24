from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("training", "0009_recovery_write_protection")]
    operations = [
        migrations.AlterModelOptions(
            name="batch",
            options={"permissions": [("coordinate_register", "Can coordinate the training register")]},
        ),
    ]
