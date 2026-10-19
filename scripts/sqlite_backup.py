"""Локальные WAL-consistent backup/restore в НОВЫЙ файл, только stdlib Python 3.11+."""

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

RESERVE = 4 * 1024**3
OWN_NAME = re.compile(r"shade-backup-\d{8}T\d{6}Z-[0-9a-f]{32}\.sqlite3")


class BackupError(Exception):
    pass


def private_directory(path: Path) -> Path:
    path = path.absolute()
    if path.resolve() != path:
        raise BackupError("UNSAFE_DIRECTORY")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise BackupError("DIRECTORY_MUST_BE_PRIVATE")
    return path


def copy_database(source: Path, destination: Path, *, timeout: float = 120) -> dict:
    source = source.absolute()
    if source.resolve() != source or not source.is_file():
        raise BackupError("INVALID_SOURCE")
    parent = private_directory(destination.parent)
    destination = parent / destination.name
    if any(
        Path(str(destination) + suffix).exists() or Path(str(destination) + suffix).is_symlink()
        for suffix in ("", "-wal", "-shm", "-journal")
    ):
        raise BackupError("DESTINATION_EXISTS")
    if not 0 < timeout <= 600:
        raise BackupError("INVALID_TIMEOUT")
    temporary = parent / (".shade-backup-" + uuid.uuid4().hex + ".partial")
    deadline = time.monotonic() + timeout

    def guard(*_):
        if time.monotonic() >= deadline:
            raise BackupError("TIMEOUT")
        if shutil.disk_usage(parent).free < RESERVE:
            raise BackupError("DISK_RESERVE")
        return 0

    installed = False
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=1)) as src:
            size = (
                src.execute("PRAGMA page_count").fetchone()[0]
                * src.execute("PRAGMA page_size").fetchone()[0]
            )
            if shutil.disk_usage(parent).free < RESERVE + size:
                raise BackupError("DISK_RESERVE")
            fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            with closing(sqlite3.connect(temporary, timeout=1)) as dst:
                src.backup(dst, pages=128, progress=guard, sleep=0.05)
                dst.set_progress_handler(guard, 1000)
                dst.execute("PRAGMA journal_mode=DELETE")
                if dst.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise BackupError("INTEGRITY_FAILED")
                if dst.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise BackupError("FOREIGN_KEYS_FAILED")
                rows = dst.execute("SELECT version_num FROM alembic_version LIMIT 2").fetchall()
                if (
                    len(rows) != 1
                    or not isinstance(rows[0][0], str)
                    or not re.fullmatch(r"[A-Za-z0-9_]{1,128}", rows[0][0])
                ):
                    raise BackupError("INVALID_SCHEMA")
                revision = rows[0][0]
            guard()
            with temporary.open("rb") as snapshot:
                checksum = hashlib.sha256()
                while chunk := snapshot.read(1024**2):
                    guard()
                    checksum.update(chunk)
                digest = checksum.hexdigest()
                os.fsync(snapshot.fileno())
            guard()
            # hard-link публикует уже проверенный снимок атомарно без overwrite.
            os.link(temporary, destination)
            installed = True
            directory_fd = os.open(parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return {
            "result": "PASS",
            "bytes": destination.stat().st_size,
            "sha256": digest,
            "revision": revision,
        }
    except (sqlite3.Error, OSError) as exc:
        raise BackupError("BACKUP_IO_OR_SQLITE_ERROR") from exc
    finally:
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(temporary) + suffix).unlink(missing_ok=True)
        # Даже при ошибке fsync опубликованная проверенная копия сохраняется.
        if installed:
            os.chmod(destination, 0o600)


def backup(source: Path, directory: Path, *, keep: int = 7) -> tuple[Path, dict]:
    if not 1 <= keep <= 30:
        raise BackupError("INVALID_RETENTION")
    directory = private_directory(directory)
    name = "shade-backup-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex
    target = directory / (name + ".sqlite3")
    result = copy_database(source, target)
    candidates = sorted(
        (
            p
            for p in directory.iterdir()
            if OWN_NAME.fullmatch(p.name)
            and not p.is_symlink()
            and p.is_file()
            and p.stat().st_uid == os.getuid()
        ),
        key=lambda p: (p.stat().st_mtime_ns, p.name),
        reverse=True,
    )
    for old in candidates[keep:]:
        if old != target and old != source.absolute():
            old.unlink()
    return target, result


def main():
    parser = argparse.ArgumentParser(description="Закрытый локальный SQLite backup/restore")
    sub = parser.add_subparsers(dest="command", required=True)
    save = sub.add_parser("backup")
    save.add_argument("--source", type=Path, required=True)
    save.add_argument("--directory", type=Path, required=True)
    save.add_argument("--keep", type=int, default=7)
    restore = sub.add_parser("restore")
    restore.add_argument("--source", type=Path, required=True)
    restore.add_argument(
        "--destination",
        type=Path,
        required=True,
        help="Только НОВЫЙ файл; перед переключением Core остановить",
    )
    args = parser.parse_args()
    try:
        if args.command == "backup":
            path, result = backup(args.source, args.directory, keep=args.keep)
        else:
            path = args.destination
            result = copy_database(args.source, path)
    except (BackupError, OSError) as exc:
        code = str(exc) if isinstance(exc, BackupError) else "BACKUP_IO_ERROR"
        parser.exit(1, "Ошибка копирования: " + code + "\n")
    print(json.dumps({**result, "file": path.name}))


if __name__ == "__main__":
    main()
