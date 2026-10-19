"""Подтверждаемые голосовые запросы без аудио и транскрипта."""

import sqlalchemy as sa
from alembic import op

revision = "0012_voice_requests"
down_revision = "0011_meeting_mode"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "voice_requests",
        sa.Column("id", sa.Text(), primary_key=True),
        *[
            sa.Column(k, sa.Text(), nullable=False)
            for k in ("payload_hash", "policy_scope", "entity_id", "action", "alias", "state")
        ],
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("event_id", sa.Integer(), nullable=True),
        sa.Column("new_state", sa.Text(), nullable=True),
        sa.Column("state_observed", sa.Integer(), nullable=False),
        *[
            sa.Column(k, sa.DateTime(), nullable=False)
            for k in ("created_at", "expires_at", "updated_at")
        ],
    )
    op.create_index("ix_voice_requests_created_at", "voice_requests", ["created_at"])


def downgrade():
    op.drop_index("ix_voice_requests_created_at", table_name="voice_requests")
    op.drop_table("voice_requests")
