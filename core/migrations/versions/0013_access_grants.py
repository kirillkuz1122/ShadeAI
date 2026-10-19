"""Одноразовые доступы Shade Keypad без открытого PIN."""

import sqlalchemy as sa
from alembic import op

revision = "0013_access_grants"
down_revision = "0012_voice_requests"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "access_grants",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("notification_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("source_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("pin_fingerprint", sa.Text(), nullable=False, unique=True),
        *[
            sa.Column(k, sa.Text(), nullable=False)
            for k in ("policy_scope", "entity_id", "pin_digest", "state")
        ],
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("bad_attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("event_id", sa.Integer(), nullable=True),
        sa.Column("new_state", sa.Text(), nullable=True),
        sa.Column("state_observed", sa.Integer(), nullable=False),
        *[
            sa.Column(k, sa.DateTime(), nullable=False)
            for k in ("created_at", "expires_at", "updated_at")
        ],
    )
    op.create_index("ix_access_grants_created_at", "access_grants", ["created_at"])
    op.create_table(
        "access_gates",
        sa.Column("entity_id", sa.Text(), primary_key=True),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("access_gates")
    op.drop_index("ix_access_grants_created_at", table_name="access_grants")
    op.drop_table("access_grants")
