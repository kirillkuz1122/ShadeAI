"""Отложенные исполнения сценариев без автоматического повтора команды."""

import sqlalchemy as sa
from alembic import op

revision = "0009_automation_runs"
down_revision = "0008_suggestions_hints"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "automation_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("identity", sa.Text(), nullable=False, unique=True),
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("approval_key", sa.Text(), nullable=False),
        sa.Column("primary_event_id", sa.Integer(), nullable=False),
        sa.Column("home_event_id", sa.Integer(), nullable=False),
        sa.Column("target_entity", sa.Text(), nullable=False),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("event_id", sa.Integer(), nullable=True),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_automation_runs_state_due", "automation_runs", ["state", "due_at"])
    op.create_index(
        "ix_automation_runs_target_started", "automation_runs", ["target_entity", "started_at"]
    )


def downgrade():
    op.drop_table("automation_runs")
