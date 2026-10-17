"""Идемпотентность, индексы очистки и непереиспользуемые ID уведомлений."""

import sqlalchemy as sa
from alembic import op

revision = "0003_notification_identity"
down_revision = "0002_device_states"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table(
        "notifications_raw", recreate="always", table_kwargs={"sqlite_autoincrement": True}
    ) as batch:
        batch.add_column(sa.Column("dedupe_key", sa.Text(), nullable=True))
        batch.add_column(sa.Column("payload_hash", sa.Text(), nullable=True))
        batch.create_index("uq_notifications_dedupe_key", ["dedupe_key"], unique=True)
        batch.create_index("ix_notifications_created_at", ["created_at"])
        batch.create_index("ix_notifications_timestamp", ["timestamp"])


def downgrade() -> None:
    with op.batch_alter_table("notifications_raw") as batch:
        batch.drop_index("uq_notifications_dedupe_key")
        batch.drop_index("ix_notifications_created_at")
        batch.drop_index("ix_notifications_timestamp")
        batch.drop_column("payload_hash")
        batch.drop_column("dedupe_key")
