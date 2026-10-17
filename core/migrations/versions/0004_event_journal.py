"""Индексы журнала и непереиспользуемые идентификаторы аудита."""

from alembic import op

revision = "0004_event_journal"
down_revision = "0003_notification_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table(
        "events_log", recreate="always", table_kwargs={"sqlite_autoincrement": True}
    ) as batch:
        batch.create_index("ix_events_timestamp", ["timestamp"])
        batch.create_index("ix_events_source_type", ["source", "event_type"])


def downgrade() -> None:
    with op.batch_alter_table("events_log") as batch:
        batch.drop_index("ix_events_source_type")
        batch.drop_index("ix_events_timestamp")
