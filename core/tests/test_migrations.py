import asyncio
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import select
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.connection import create_db_engine
from app.db.migrations import CORE_DIR, migration_config, upgrade_database
from app.db.models import DeviceState, NotificationRaw

# Независимый снимок DDL скелета до TASK-04, без импорта схемы из миграции.
LEGACY_SQL = """
CREATE TABLE notifications_raw (
    id INTEGER NOT NULL PRIMARY KEY,
    app_name TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    priority TEXT NOT NULL,
    category TEXT,
    extracted_data_json TEXT,
    is_processed INTEGER NOT NULL,
    created_at DATETIME NOT NULL
);
CREATE TABLE events_log (
    id INTEGER NOT NULL PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    processed INTEGER NOT NULL
);
"""


def legacy_database(path, sql=LEGACY_SQL, *, seed=False):
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(sql)
        if seed:
            db.executemany(
                "INSERT INTO notifications_raw VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        41,
                        "test.app",
                        "Тест",
                        "Синтетический текст",
                        "2026-10-17T10:00:00Z",
                        "default",
                        None,
                        None,
                        0,
                        "2026-10-17 10:00:01",
                    ),
                    (
                        73,
                        "test.app",
                        "Проверено",
                        "Без персональных данных",
                        "2026-10-17T11:00:00Z",
                        "high",
                        "noise",
                        '{"synthetic": true}',
                        1,
                        "2026-10-17 11:00:01",
                    ),
                ],
            )
            db.execute(
                "INSERT INTO events_log VALUES (?, ?, ?, ?, ?, ?)",
                (19, "2026-10-17 10:00:01", "test", "synthetic", '{"id": 41}', 1),
            )


def snapshot(path):
    with closing(sqlite3.connect(path)) as db:
        schema = db.execute(
            "SELECT name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        rows = {
            name: db.execute(f'SELECT * FROM "{name}" ORDER BY id').fetchall()
            for name in ("notifications_raw", "events_log")
            if any(item[0] == name for item in schema)
        }
        if "notifications_raw" in rows:
            columns = [c[1] for c in db.execute("PRAGMA table_info(notifications_raw)")]
            keep = [
                i for i, name in enumerate(columns) if name not in {"dedupe_key", "payload_hash"}
            ]
            rows["notifications_raw"] = [
                tuple(row[i] for i in keep) for row in rows["notifications_raw"]
            ]
        return schema, rows


async def migrate(path, revision="head"):
    engine = create_db_engine(f"sqlite+aiosqlite:///{path}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda conn: command.upgrade(migration_config(conn), revision)
            )
    finally:
        await engine.dispose()


def test_empty_database_schema_and_device_constraints(tmp_path):
    path = tmp_path / "empty.db"
    asyncio.run(migrate(path))

    async def scenario():
        engine = create_db_engine(f"sqlite+aiosqlite:///{path}")
        try:
            async with engine.connect() as connection:
                differences = await connection.run_sync(
                    lambda conn: compare_metadata(
                        MigrationContext.configure(conn, opts={"compare_server_default": True}),
                        Base.metadata,
                    )
                )
                assert differences == []
                head = ScriptDirectory.from_config(migration_config()).get_current_head()
                assert (
                    await connection.exec_driver_sql("SELECT version_num FROM alembic_version")
                ).scalar_one() == head
                assert (
                    await connection.exec_driver_sql("PRAGMA journal_mode")
                ).scalar_one() == "wal"
                assert (await connection.exec_driver_sql("PRAGMA foreign_keys")).scalar_one() == 1
                assert (await connection.exec_driver_sql("PRAGMA synchronous")).scalar_one() == 1
            async with engine.begin() as connection:
                await connection.exec_driver_sql(
                    "INSERT INTO device_states (entity_id, state, last_changed, last_updated) "
                    "VALUES ('light.test', 'on', '2026-10-17 10:00:00', '2026-10-17 10:01:00')"
                )
            async with AsyncSession(engine) as session:
                state = await session.get(DeviceState, "light.test")
                assert state.state == "on"
                assert state.attributes_json == "{}"
                assert state.last_updated == datetime(2026, 10, 17, 10, 1)
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.exec_driver_sql(
                        "INSERT INTO device_states SELECT * FROM device_states"
                    )
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.exec_driver_sql(
                        "INSERT INTO device_states (entity_id, state) VALUES ('light.other', 'on')"
                    )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_legacy_data_survives_migrations_and_restarts(tmp_path):
    path = tmp_path / "legacy.db"
    legacy_database(path, seed=True)
    original_schema, original_rows = snapshot(path)
    asyncio.run(migrate(path, "0002_device_states"))
    baseline_schema, rows = snapshot(path)
    assert rows == original_rows
    assert all(item in baseline_schema for item in original_schema)
    asyncio.run(migrate(path))
    upgraded_schema, rows = snapshot(path)
    assert rows == original_rows
    for _ in range(2):
        asyncio.run(migrate(path))
        assert snapshot(path) == (upgraded_schema, original_rows)

    async def scenario():
        engine = create_db_engine(f"sqlite+aiosqlite:///{path}")
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                assert (await session.get(NotificationRaw, 73)).extracted_data_json == (
                    '{"synthetic": true}'
                )
                row = NotificationRaw(
                    app_name="test.app",
                    title="После миграции",
                    text="Тест",
                    timestamp="2026-10-17T12:00:00Z",
                )
                session.add(row)
                await session.commit()
                assert row.id > 73
                assert row.priority == "default"
                assert row.is_processed == 0
        finally:
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "sql",
    [
        LEGACY_SQL.split("CREATE TABLE events_log")[0],
        LEGACY_SQL.replace("title TEXT", "title INTEGER"),
        LEGACY_SQL.replace("category TEXT,", "category TEXT NOT NULL,"),
        LEGACY_SQL.replace("    category TEXT,\n", ""),
        LEGACY_SQL.replace("PRIMARY KEY", ""),
        LEGACY_SQL + "CREATE TABLE unrelated (id INTEGER PRIMARY KEY);",
        LEGACY_SQL + "CREATE VIEW custom_view AS SELECT id FROM notifications_raw;",
        LEGACY_SQL + "CREATE UNIQUE INDEX custom_index ON notifications_raw(title);",
    ],
    ids=[
        "partial",
        "type",
        "nullable",
        "missing-column",
        "primary-key",
        "extra-table",
        "view",
        "index",
    ],
)
def test_unknown_legacy_schema_is_rejected_without_changes(tmp_path, sql):
    path = tmp_path / "unknown.db"
    legacy_database(path, sql, seed=sql.startswith(LEGACY_SQL))
    original = snapshot(path)
    with pytest.raises(CommandError, match="Неизвестная схема БД"):
        asyncio.run(migrate(path))
    assert snapshot(path) == original


def test_failed_device_migration_rolls_back_version_and_schema(tmp_path, monkeypatch):
    path = tmp_path / "failure.db"
    legacy_database(path, seed=True)
    original = snapshot(path)
    create_table = Operations.create_table

    def create_then_fail(self, *args, **kwargs):
        create_table(self, *args, **kwargs)
        raise RuntimeError("сбой после создания таблицы")

    with monkeypatch.context() as patch:
        patch.setattr(Operations, "create_table", create_then_fail)
        with pytest.raises(RuntimeError, match="сбой после создания таблицы"):
            asyncio.run(migrate(path))
    assert snapshot(path) == original
    asyncio.run(migrate(path))
    assert snapshot(path)[1] == original[1]


def test_sqlite_rolls_back_ddl_and_enforces_foreign_keys(tmp_path):
    async def scenario():
        engine = create_db_engine(f"sqlite+aiosqlite:///{tmp_path / 'transaction.db'}")
        try:
            with pytest.raises(RuntimeError, match="сбой миграции"):
                async with engine.begin() as connection:
                    await connection.exec_driver_sql("CREATE TABLE rollback_probe (id INTEGER)")
                    raise RuntimeError("сбой миграции")
            async with engine.begin() as connection:
                assert (
                    await connection.exec_driver_sql(
                        "SELECT name FROM sqlite_master WHERE name='rollback_probe'"
                    )
                ).first() is None
                await connection.exec_driver_sql("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
                await connection.exec_driver_sql(
                    "CREATE TABLE child (parent_id INTEGER REFERENCES parent(id))"
                )
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.exec_driver_sql("INSERT INTO child VALUES (999)")
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_versioned_baseline_upgrade_and_device_downgrade(tmp_path):
    path = tmp_path / "versioned.db"

    async def scenario():
        engine = create_db_engine(f"sqlite+aiosqlite:///{path}")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda conn: command.upgrade(migration_config(conn), "0001_legacy_schema")
                )
            async with engine.begin() as connection:
                await connection.exec_driver_sql(
                    "INSERT INTO notifications_raw "
                    "(app_name,title,text,timestamp,priority,is_processed,created_at) "
                    "VALUES ('test','Тест','Тест','2026-10-17T10:00:00Z','default',0,"
                    "'2026-10-17 10:00:00')"
                )
            async with engine.begin() as connection:
                await connection.run_sync(upgrade_database)
                await connection.run_sync(
                    lambda conn: command.downgrade(migration_config(conn), "0001_legacy_schema")
                )
            async with AsyncSession(engine) as session:
                assert (await session.scalar(select(NotificationRaw.id))) == 1
            async with engine.begin() as connection:
                await connection.run_sync(upgrade_database)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_alembic_cli_uses_configured_database_outside_core(tmp_path):
    path = tmp_path / "cli%database.db"
    env = dict(os.environ, DB_URL=str(URL.create("sqlite+aiosqlite", database=str(path))))
    args = [sys.executable, "-m", "alembic", "-c", str(CORE_DIR / "alembic.ini")]
    for action in [["upgrade", "head"], ["current"], ["check"]]:
        result = subprocess.run(
            [*args, *action], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, result.stdout + result.stderr
        if action == ["current"]:
            head = ScriptDirectory.from_config(migration_config()).get_current_head()
            assert f"{head} (head)" in result.stdout
    assert path.is_file()
    assert not (tmp_path / "shade.db").exists()


def test_sensor_history_upgrade_downgrade_preserves_existing_data(tmp_path):
    path = tmp_path / "telemetry.db"
    legacy_database(path, seed=True)
    asyncio.run(migrate(path, "0004_event_journal"))
    original = snapshot(path)[1]
    asyncio.run(migrate(path))
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "INSERT INTO sensor_history (entity_id, state, attributes_json, source, observed_at) "
            "VALUES ('sensor.test', '21', '{}', 'ha_snapshot', '2026-10-18 01:00:00')"
        )
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("SELECT ha_timestamp FROM sensor_history").fetchone() == (None,)
    assert snapshot(path)[1] == original

    async def downgrade():
        engine = create_db_engine(f"sqlite+aiosqlite:///{path}")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda conn: command.downgrade(migration_config(conn), "0004_event_journal")
                )
        finally:
            await engine.dispose()

    asyncio.run(downgrade())
    assert snapshot(path)[1] == original
    asyncio.run(migrate(path))
    assert snapshot(path)[1] == original
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT count(*) FROM sensor_history").fetchone() == (0,)
