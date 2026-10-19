import hashlib
import importlib.util
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "sqlite_backup", Path(__file__).resolve().parents[2] / "scripts/sqlite_backup.py"
)
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


@pytest.fixture(autouse=True)
def synthetic_disk_budget(monkeypatch):
    # БД тестов — несколько страниц; CI tmpfs128MiB не является deployment-диском.
    # Настоящий резерв проверяется отдельным loopback, отказы — явным override ниже.
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda _: SimpleNamespace(free=8 * 1024**3))


@pytest.fixture
def database(tmp_path):
    source = tmp_path / "source.db"
    conn = sqlite3.connect(source)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE alembic_version(version_num TEXT)")
    conn.execute("INSERT INTO alembic_version VALUES ('0013')")
    conn.execute("CREATE TABLE records(id INTEGER PRIMARY KEY, text TEXT)")
    conn.execute("INSERT INTO records VALUES (1, 'synthetic committed')")
    conn.commit()
    yield source, conn
    conn.close()


def read_rows(path):
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        return conn.execute("SELECT * FROM records").fetchall()


def test_live_wal_backup_and_restore(database, tmp_path):
    source, writer = database
    assert Path(str(source) + "-wal").stat().st_size > 0
    writer.execute("INSERT INTO records VALUES (2, 'uncommitted')")
    path, result = backup.backup(source, tmp_path / "backups")
    assert result["result"] == "PASS" and result["revision"] == "0013"
    assert read_rows(path) == [(1, "synthetic committed")]
    writer.rollback()
    writer.execute("INSERT INTO records VALUES (3, 'later')")
    writer.commit()
    restored = tmp_path / "restore/new.db"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    restored_result = backup.copy_database(path, restored)
    assert before == result["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert restored_result["sha256"] == hashlib.sha256(restored.read_bytes()).hexdigest()
    assert read_rows(restored) == [(1, "synthetic committed")]
    assert read_rows(source) == [(1, "synthetic committed"), (3, "later")]
    assert path.stat().st_mode & 0o777 == restored.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert writer.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
def test_refuse_existing_targets(database, tmp_path, suffix):
    target = tmp_path / "restored.db"
    occupied = Path(str(target) + suffix)
    occupied.write_bytes(b"preserve")
    with pytest.raises(backup.BackupError, match="DESTINATION_EXISTS"):
        backup.copy_database(database[0], target)
    assert occupied.read_bytes() == b"preserve"


def test_symlinks_and_directory_permissions(database, tmp_path):
    source, _ = database
    link = tmp_path / "link.db"
    link.symlink_to(source)
    with pytest.raises(backup.BackupError, match="INVALID_SOURCE"):
        backup.copy_database(link, tmp_path / "new.db")
    folder = tmp_path / "public"
    folder.mkdir(mode=0o755)
    with pytest.raises(backup.BackupError, match="DIRECTORY_MUST_BE_PRIVATE"):
        backup.backup(source, folder)
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(backup.BackupError, match="UNSAFE_DIRECTORY"):
        backup.copy_database(source, alias / "new.db")
    dangling = tmp_path / "dangling.db"
    dangling.symlink_to(tmp_path / "absent")
    with pytest.raises(backup.BackupError, match="DESTINATION_EXISTS"):
        backup.copy_database(source, dangling)


def test_disk_and_deadline_cleanup(database, tmp_path, monkeypatch):
    target = tmp_path / "new.db"
    with monkeypatch.context() as patch:
        patch.setattr(backup.shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
        with pytest.raises(backup.BackupError, match="DISK_RESERVE"):
            backup.copy_database(database[0], target)
    times = iter([0, 500])
    monkeypatch.setattr(backup.time, "monotonic", lambda: next(times, 500))
    with pytest.raises(backup.BackupError, match="TIMEOUT"):
        backup.copy_database(database[0], target)
    assert not target.exists() and not list(tmp_path.glob(".shade-backup-*"))


def test_failed_copy_does_not_prune_and_retention_preserves_foreign(database, tmp_path):
    directory = tmp_path / "backups"
    first, _ = backup.backup(database[0], directory, keep=1)
    foreign = directory / "manual.sqlite3"
    foreign.write_text("keep")
    link = directory / ("shade-backup-20000101T000000Z-" + "a" * 32 + ".sqlite3")
    link.symlink_to(foreign)
    invalid = tmp_path / "invalid.db"
    with closing(sqlite3.connect(invalid)) as conn:
        conn.execute("CREATE TABLE unrelated(id)")
    with pytest.raises(backup.BackupError):
        backup.backup(invalid, directory, keep=1)
    assert first.exists()
    os.utime(first, (1, 1))
    latest, _ = backup.backup(database[0], directory, keep=1)
    assert not first.exists() and latest.exists() and link.is_symlink()
    assert foreign.read_text() == "keep" and not list(directory.glob("*.partial"))
