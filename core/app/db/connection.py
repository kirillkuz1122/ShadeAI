from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    # BEGIN задаёт SQLAlchemy: иначе sqlite3 может коммитить DDL вне транзакции.
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def _begin_sqlite(connection: Connection) -> None:
    connection.exec_driver_sql("BEGIN")


def create_db_engine(db_url: str) -> AsyncEngine:
    engine = create_async_engine(db_url)
    if engine.dialect.name == "sqlite":
        event.listen(engine.sync_engine, "connect", _set_sqlite_pragma)
        event.listen(engine.sync_engine, "begin", _begin_sqlite)
    return engine
