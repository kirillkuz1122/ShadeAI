"""Начальная схема: пустая БД или проверенный скелет до Alembic."""

import sqlalchemy as sa
from alembic import op
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.util import CommandError

revision = "0001_legacy_schema"
down_revision = None
branch_labels = None
depends_on = None


def legacy_metadata() -> sa.MetaData:
    # Снимок схемы скелета: не импортировать изменяющиеся модели приложения.
    metadata = sa.MetaData()
    sa.Table(
        "notifications_raw",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("app_name", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.Text(), nullable=False),
        sa.Column("priority", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("extracted_data_json", sa.Text(), nullable=True),
        sa.Column("is_processed", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    sa.Table(
        "events_log",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False),
    )
    return metadata


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing = set(inspector.get_table_names()) - {"alembic_version"}
    metadata = legacy_metadata()
    error = CommandError(
        "Неизвестная схема БД: ожидается пустая БД или полный скелет Shade Core. "
        "Миграция отменена; проверьте структуру на резервной копии. Не используйте stamp head."
    )
    if inspector.get_view_names():
        raise error
    if not existing:
        for table in metadata.sorted_tables:
            table.create(connection)
        return
    if existing != set(metadata.tables):
        raise error
    migration_context = MigrationContext.configure(
        connection, opts={"compare_type": True, "compare_server_default": True}
    )
    if compare_metadata(migration_context, metadata):
        raise error
    for name in existing:
        if inspector.get_pk_constraint(name)["constrained_columns"] != ["id"]:
            raise error
        if inspector.get_check_constraints(name):
            raise error


def downgrade() -> None:
    op.drop_table("events_log")
    op.drop_table("notifications_raw")
