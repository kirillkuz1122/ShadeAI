"""Manifest уже подготовленного локального Vosk bundle; никакой загрузки."""

import argparse
import hashlib
import json
from pathlib import Path

MANIFEST = "shade-model.json"
MAX_BYTES = 192 * 1024**2


def inventory(root: Path) -> list[dict]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("STT_MODEL_INVALID")
    entries, total = [], 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("STT_MODEL_INVALID")
        if path.is_dir() or path.name == MANIFEST:
            continue
        size = path.stat().st_size
        total += size
        if len(entries) >= 256 or total > MAX_BYTES or not 0 < size <= MAX_BYTES:
            raise ValueError("STT_MODEL_INVALID")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        entries.append(
            dict(path=path.relative_to(root).as_posix(), size=size, sha256=digest.hexdigest())
        )
    if not entries:
        raise ValueError("STT_MODEL_INVALID")
    return entries


def validate(root: Path, expected: str) -> None:
    manifest = root / MANIFEST
    if manifest.is_symlink() or manifest.stat().st_size > 65536:
        raise ValueError("STT_MODEL_INVALID")
    data = manifest.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("STT_MODEL_MISMATCH")
    content = json.loads(data)
    if content != dict(version=1, files=inventory(root)):
        raise ValueError("STT_MODEL_MISMATCH")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_path", type=Path)
    args = parser.parse_args()
    path = args.model_path / MANIFEST
    if path.exists():
        raise SystemExit("Manifest уже есть; сначала проверьте существующий bundle")
    data = json.dumps(
        dict(version=1, files=inventory(args.model_path)), sort_keys=True, separators=(",", ":")
    ).encode()
    with path.open("xb") as output:
        path.chmod(0o600)
        output.write(data)
    print(hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    main()
