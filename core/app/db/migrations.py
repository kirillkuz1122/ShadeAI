from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection

CORE_DIR = Path(__file__).resolve().parents[2]


def migration_config(connection: Connection | None = None) -> Config:
    config = Config(str(CORE_DIR / "alembic.ini"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def upgrade_database(connection: Connection) -> None:
    command.upgrade(migration_config(connection), "head")
