"""Предложения, история решений и локальная лента подсказок."""

import sqlalchemy as sa
from alembic import op

revision = "0008_suggestions_hints"
down_revision = "0007_habit_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automation_rules",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("source_habit_id", sa.Text(), nullable=False, unique=True),
        sa.Column("profile_key", sa.Text(), nullable=False),
        sa.Column("config_key", sa.Text(), nullable=False),
        sa.Column("trigger_json", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source_stale", sa.Integer(), nullable=False),
        sa.Column("target_entity", sa.Text(), nullable=True),
        sa.Column("approval_key", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "automation_decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("target_entity", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_automation_decisions_rule", "automation_decisions", ["rule_id", "id"])
    op.create_table(
        "local_hints",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("config_key", sa.Text(), nullable=False),
        sa.Column("presence_event_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("notification_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_table(
        "local_hint_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("feed_id", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("local_hint_state")
    op.drop_table("local_hints")
    op.drop_index("ix_automation_decisions_rule", "automation_decisions")
    op.drop_table("automation_decisions")
    op.drop_table("automation_rules")
