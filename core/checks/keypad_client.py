"""Ручной локальный эмулятор Shade Keypad, без ключа владельца и PIN в argv."""

import argparse
import getpass
import ipaddress
import os
import re
from urllib.parse import urlsplit

import httpx


def local_url(value):
    try:
        parsed = urlsplit(value)
        address = ipaddress.ip_address(parsed.hostname or "")
        if (
            parsed.scheme not in {"http", "https"}
            or not address.is_private
            or address.is_unspecified
            or address.is_multicast
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path.rstrip("/") != "/api/v1"
        ):
            raise ValueError
        _ = parsed.port
        return value.rstrip("/") + "/access/keypad/verify"
    except (ValueError, TypeError):
        raise ValueError(
            "Нужен локальный IP-адрес Core и путь /api/v1, без секретов в URL"
        ) from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entity", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"lock\.[a-z0-9_]{1,249}", args.entity):
        parser.error("Нужен конкретный lock entity_id")
    try:
        url = local_url(os.environ.get("SHADE_KEYPAD_URL", ""))
    except ValueError as error:
        parser.error(str(error))
    token = os.environ.get("ACCESS_KEYPAD_TOKEN", "")
    if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
        parser.error("Нужен отдельный ACCESS_KEYPAD_TOKEN >=32 ASCII-знаков без пробелов")
    pin = getpass.getpass("Одноразовый PIN (ввод скрыт): ")
    if not re.fullmatch(r"[0-9]{6}", pin):
        parser.error("PIN должен содержать шесть цифр")
    try:
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=35) as client:
            response = client.post(
                url,
                headers={"Authorization": "Bearer " + token},
                json={"entity_id": args.entity, "pin": pin},
            )
        pin = ""
        if response.status_code != 200:
            print(f"Доступ не подтверждён: HTTP {response.status_code}. Автоповтора нет.")
            return 1
        state = response.json().get("state")
        print(
            {
                "used": "HA принял unlock. Физическую дверь проверить отдельно.",
                "failed": "Команда не отправлена или отклонена. Код уже потреблён.",
                "unknown": "Результат неизвестен. Проверить дверь вручную; не повторять.",
            }.get(state, "Неподдерживаемый ответ. Проверить дверь вручную.")
        )
        return 0 if state == "used" else 1
    except (httpx.HTTPError, ValueError):
        print("Связь/результат не подтверждены. Проверить дверь вручную; автоповтора нет.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
