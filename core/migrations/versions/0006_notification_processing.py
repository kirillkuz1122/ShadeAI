"""Состояния и метаданные очереди обработки уведомлений."""

import sqlalchemy as sa
from alembic import op

revision = "0006_notification_processing"
down_revision = "0005_sensor_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notifications_raw",
        sa.Column("processing_status", sa.Text(), nullable=False, server_default="pending"),
    )
    op.add_column(
        "notifications_raw",
        sa.Column("processing_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("notifications_raw", sa.Column("processing_error_code", sa.Text(), nullable=True))
    op.add_column(
        "notifications_raw", sa.Column("processing_started_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "notifications_raw", sa.Column("processing_finished_at", sa.DateTime(), nullable=True)
    )
    op.create_index("ix_notifications_processing", "notifications_raw", ["processing_status", "id"])


def downgrade() -> None:
    connection = op.get_bind()
    previous_sequence = None
    if connection.dialect.name == "sqlite":
        previous_sequence = connection.scalar(
            sa.text("SELECT seq FROM sqlite_sequence WHERE name='notifications_raw'")
        )
    with op.batch_alter_table(
        "notifications_raw", table_kwargs={"sqlite_autoincrement": True}
    ) as batch:
        batch.drop_index("ix_notifications_processing")
        batch.drop_column("processing_finished_at")
        batch.drop_column("processing_started_at")
        batch.drop_column("processing_error_code")
        batch.drop_column("processing_attempts")
        batch.drop_column("processing_status")
    if previous_sequence is not None:
        connection.execute(
            sa.text(
                "INSERT INTO sqlite_sequence(name, seq) SELECT 'notifications_raw', :seq "
                "WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name='notifications_raw')"
            ),
            {"seq": previous_sequence},
        )
        connection.execute(
            sa.text("UPDATE sqlite_sequence SET seq=MAX(seq, :seq) WHERE name='notifications_raw'"),
            {"seq": previous_sequence},
        )
