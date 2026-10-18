"""Ручная подготовка pinned GGUF; приложение никогда не скачивает модель."""

import argparse
import fcntl
import hashlib
import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def download(name):
    models = json.loads((ROOT / "scripts/models.json").read_text())
    spec = models[name]
    folder = ROOT / "core/models"
    folder.mkdir(exist_ok=True)
    target = folder / spec["file"]
    partial = target.with_suffix(".gguf.part")
    with (folder / (spec["file"] + ".lock")).open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (
            target.exists()
            and target.stat().st_size == spec["bytes"]
            and digest(target) == spec["sha256"]
        ):
            print(f"Проверена существующая модель: {target.name}")
            return
        # Повреждённый готовый файл не перезаписываем: замена только после проверки нового.
        url = f"https://huggingface.co/{spec['repo']}/resolve/{spec['revision']}/{spec['file']}"
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > spec["bytes"]:
            partial.unlink()
            offset = 0
        request = urllib.request.Request(
            url, headers={"Range": f"bytes={offset}-"} if offset else {}
        )
        print(f"Загрузка {target.name}; ожидается {spec['bytes']} байт", flush=True)
        if offset < spec["bytes"]:
            with urllib.request.urlopen(request, timeout=60) as response:
                resumed = offset and response.status == 206
                if resumed and not response.headers.get("Content-Range", "").startswith(
                    f"bytes {offset}-"
                ):
                    raise RuntimeError("Неверное продолжение загрузки")
                with partial.open("ab" if resumed else "wb") as output:
                    total = offset if resumed else 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > spec["bytes"]:
                            raise RuntimeError("Ответ превышает размер модели")
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
        if partial.stat().st_size != spec["bytes"] or digest(partial) != spec["sha256"]:
            partial.unlink(missing_ok=True)
            raise RuntimeError("Размер/SHA-256 не совпали; модель не установлена")
        partial.replace(target)
        print(f"SHA-256 совпал: {target.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("tinyllama", "qwen"), default="tinyllama")
    download(parser.parse_args().model)
