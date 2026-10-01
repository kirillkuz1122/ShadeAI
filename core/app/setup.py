"""Локальная настройка .env без загрузки приложения и вывода секретов."""

import argparse
import os
import re
import secrets
import tempfile
from pathlib import Path

from dotenv import dotenv_values

from app.core.credentials import PLACEHOLDER_KEYS, validate_api_key


def initialize_env(path: Path) -> bool:
    if path.is_symlink():
        raise ValueError("Файл настроек не должен быть символической ссылкой")

    if path.exists():
        content = path.read_text(encoding="utf-8")
        value = dotenv_values(path, interpolate=False).get("SHADE_API_KEY")
        if value is not None and value not in PLACEHOLDER_KEYS:
            validate_api_key(value)
            path.chmod(0o600)
            return False
    else:
        template = Path(__file__).resolve().parents[1] / ".env.example"
        content = template.read_text(encoding="utf-8")

    key_line = f"SHADE_API_KEY={secrets.token_urlsafe(32)}"
    content, count = re.subn(
        r"(?m)^[ \t]*(?:export[ \t]+)?SHADE_API_KEY[ \t]*=.*$", key_line, content
    )
    if not count:
        content = content.rstrip("\n") + "\n" + key_line + "\n"

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".shade-env-", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            os.fchmod(temporary.fileno(), 0o600)
            temporary.write(content)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Настроить локальный ключ Shade Core")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Путь к файлу .env")
    args = parser.parse_args()
    try:
        generated = initialize_env(args.env_file)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Ошибка настройки: {exc}\n")
    message = "Ключ создан" if generated else "Существующий ключ сохранён"
    print(f"{message}; файл {args.env_file}, права 600. Значение ключа не выводится.")


if __name__ == "__main__":
    main()
