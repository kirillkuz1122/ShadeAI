"""Описательные профили присутствия и снимок последнего анализа."""

import sqlalchemy as sa
from alembic import op

revision = "0007_habit_profiles"
down_revision = "0006_notification_processing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "habit_profiles",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("day_group", sa.Text(), nullable=False),
        sa.Column("config_key", sa.Text(), nullable=False),
        sa.Column("profile_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "uq_habit_profile_scope",
        "habit_profiles",
        ["entity_id", "timezone", "kind", "day_group"],
        unique=True,
    )
    op.create_table(
        "analytics_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("config_key", sa.Text(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("analytics_state")
    op.drop_index("uq_habit_profile_scope", "habit_profiles")
    op.drop_table("habit_profiles")
