"""Ограниченная история датчиков и интервалы недоступности телеметрии."""

import sqlalchemy as sa
from alembic import op

revision = "0005_sensor_history"
down_revision = "0004_event_journal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sensor_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("attributes_json", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("ha_timestamp", sa.DateTime(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_sensor_history_entity_id", "sensor_history", ["entity_id", "id"])
    op.create_index("ix_sensor_history_observed_at", "sensor_history", ["observed_at"])
    op.create_table(
        "telemetry_gaps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_table(
        "telemetry_checkpoint",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_seen", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("telemetry_checkpoint")
    op.drop_table("telemetry_gaps")
    op.drop_table("sensor_history")
