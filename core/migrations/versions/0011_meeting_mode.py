"""Подтверждённые встречи и общее владение DND-переключателем."""

import sqlalchemy as sa
from alembic import op

revision = "0011_meeting_mode"
down_revision = "0010_calendar_events"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "meeting_plans",
        sa.Column("event_id", sa.Text(), primary_key=True),
        *[
            sa.Column(k, sa.Text(), nullable=False)
            for k in ("calendar_scope", "policy_scope", "targets_json", "started_json", "status")
        ],
        sa.Column("event_revision", sa.Integer(), nullable=False),
        *[
            sa.Column(k, sa.DateTime(), nullable=False)
            for k in ("starts_at", "ends_at", "updated_at")
        ],
    )
    op.create_table(
        "meeting_leases",
        sa.Column("entity_id", sa.Text(), primary_key=True),
        *[
            sa.Column(k, sa.Text(), nullable=False)
            for k in ("generation", "state", "members_json", "reason")
        ],
        sa.Column("context_hash", sa.Text(), nullable=True),
        *[
            sa.Column(k, sa.DateTime(), nullable=True)
            for k in ("last_changed", "last_updated", "retry_at")
        ],
        sa.Column("event_id", sa.Integer(), nullable=True),
        *[sa.Column(k, sa.DateTime(), nullable=False) for k in ("created_at", "updated_at")],
    )
    op.create_table(
        "meeting_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        *[
            sa.Column(k, sa.Text(), nullable=False)
            for k in ("entity_id", "generation", "state", "reason")
        ],
        sa.Column("event_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sqlite_autoincrement=True,
    )


def downgrade():
    op.drop_table("meeting_log")
    op.drop_table("meeting_leases")
    op.drop_table("meeting_plans")
