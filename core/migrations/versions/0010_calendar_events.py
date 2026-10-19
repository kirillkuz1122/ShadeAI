"""Локальный кэш календаря и атомарный снимок синхронизации."""

import sqlalchemy as sa
from alembic import op

revision = "0010_calendar_events"
down_revision = "0009_automation_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "calendar_events",
        sa.Column("id", sa.Text(), primary_key=True),
        *[
            sa.Column(name, sa.Text(), nullable=False)
            for name in ("config_key", "uid_hash", "recurrence", "summary", "status")
        ],
        sa.Column("location", sa.Text(), nullable=True),
        *[
            sa.Column(name, sa.DateTime(), nullable=False)
            for name in ("starts_at", "ends_at", "created_at", "updated_at")
        ],
        sa.Column("start_date", sa.Text(), nullable=True),
        sa.Column("end_date", sa.Text(), nullable=True),
        sa.Column("busy", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_calendar_events_scope_start", "calendar_events", ["config_key", "starts_at", "id"]
    )
    op.create_table(
        "calendar_sync_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("config_key", sa.Text(), nullable=False),
        sa.Column("last_attempt", sa.DateTime(), nullable=False),
        *[
            sa.Column(name, sa.DateTime(), nullable=True)
            for name in ("last_success", "window_start", "window_end")
        ],
        sa.Column("error_code", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_table("calendar_sync_state")
    op.drop_table("calendar_events")
