from django.db import migrations


TABLES = ("batch", "trainee", "session", "attendance", "approval", "correction")
OPERATIONS = ("INSERT", "UPDATE", "DELETE")

PENDING = """
CREATE VIEW training_pending_recovery AS
WITH latest AS (
    SELECT id, actor, context, CASE
        WHEN instr(context, char(10)) > 0 AND json_valid(substr(context, instr(context, char(10)) + 1))
        THEN substr(context, instr(context, char(10)) + 1)
        ELSE '{}'
    END AS payload
    FROM training_auditentry
    WHERE reason = 'Recovery required'
    ORDER BY id DESC LIMIT 1
), results AS (
    SELECT id, seed_key, note, CASE
        WHEN instr(context, char(10)) > 0 AND json_valid(substr(context, instr(context, char(10)) + 1))
        THEN substr(context, instr(context, char(10)) + 1)
        ELSE '{}'
    END AS payload
    FROM training_auditentry
    WHERE reason = 'Recovery reconciled'
)
SELECT latest.id FROM latest
WHERE NOT EXISTS (
    SELECT 1 FROM results
    WHERE results.id > latest.id
      AND results.seed_key = 'recovery-reconciled:' || latest.id
      AND length(trim(results.note)) > 0
      AND latest.actor = 'Restore command'
      AND json_type(latest.payload, '$.version') = 'integer'
      AND json_extract(latest.payload, '$.version') = 1
      AND json_extract(latest.payload, '$.action') = 'recovery_required'
      AND json_extract(latest.payload, '$.source') = 'restore'
      AND json_type(latest.payload, '$.retained_event_count') = 'integer'
      AND json_extract(latest.payload, '$.retained_event_count') >= 0
      AND json_type(latest.payload, '$.backup_reference') = 'text'
      AND length(json_extract(latest.payload, '$.backup_reference')) > 0
      AND json_type(results.payload, '$.version') = 'integer'
      AND json_extract(results.payload, '$.version') = 1
      AND json_type(results.payload, '$.marker_id') = 'integer'
      AND json_extract(results.payload, '$.marker_id') = latest.id
      AND json_extract(results.payload, '$.marker_context') = latest.context
      AND length(json_extract(results.payload, '$.marker_digest')) = 64
      AND json_extract(results.payload, '$.marker_digest') NOT GLOB '*[^0-9a-f]*'
      AND length(json_extract(results.payload, '$.evidence_digest')) = 64
      AND json_extract(results.payload, '$.evidence_digest') NOT GLOB '*[^0-9a-f]*'
      AND json_type(results.payload, '$.actor_id') = 'integer'
      AND json_extract(results.payload, '$.actor_id') > 0
)
"""


class Migration(migrations.Migration):
    dependencies = [("training", "0008_batch_protection")]
    operations = [
        migrations.RunSQL(PENDING, "DROP VIEW training_pending_recovery"),
        *[
            migrations.RunSQL(
                f"""CREATE TRIGGER quarantine_{table}_{operation.lower()}
                    BEFORE {operation} ON training_{table}
                    WHEN EXISTS (SELECT 1 FROM training_pending_recovery)
                    BEGIN SELECT RAISE(ABORT, 'Recovery reconciliation required'); END""",
                f"DROP TRIGGER quarantine_{table}_{operation.lower()}",
            )
            for table in TABLES for operation in OPERATIONS
        ],
    ]
