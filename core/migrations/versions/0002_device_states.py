"""Хранилище последних состояний сущностей Home Assistant."""

import sqlalchemy as sa
from alembic import op

revision = "0002_device_states"
down_revision = "0001_legacy_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_states",
        sa.Column("entity_id", sa.Text(), primary_key=True, nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("attributes_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("last_changed", sa.DateTime(), nullable=False),
        sa.Column("last_updated", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("device_states")
