"""UI-приёмка TASK-09: только emulator-5554 и отдельный checks/core_server.py."""

import json
import re
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from core_server import API_KEY

ROOT = Path(__file__).resolve().parents[2]
ADB = ROOT / "android/.gradle/sdk/platform-tools/adb"
PACKAGE = "com.shadeai.app"
URL = "http://127.0.0.1:8000/api/v1/"
WRONG_KEY = "task09-incorrect-key-000000000000000"


def adb(*args: str) -> str:
    return subprocess.check_output([str(ADB), "-s", "emulator-5554", *args], text=True)


def dump():
    for _ in range(3):
        reply = adb("shell", "uiautomator", "dump", "/sdcard/task09-ui.xml")
        if "dumped to" in reply:
            return ET.fromstring(adb("exec-out", "cat", "/sdcard/task09-ui.xml"))
        time.sleep(0.3)
    raise AssertionError("UI Automator не получил актуальную иерархию")


def nodes(text: str):
    return [
        node
        for node in dump().iter("node")
        if text in node.get("text", "") or text == node.get("content-desc")
    ]


def scroll(top: bool = False):
    adb(
        "shell",
        "input",
        "swipe",
        "500",
        "550" if top else "1550",
        "500",
        "1550" if top else "550",
        "200",
    )


def tap(node):
    x1, y1, x2, y2 = map(int, re.findall(r"\d+", node.attrib["bounds"]))
    adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))


def find(text: str, top: bool = False):
    for _ in range(6):
        found = nodes(text)
        if found:
            return found[0]
        scroll(top)
    raise AssertionError(f"UI: не найдено {text}")


def wait(text: str):
    for _ in range(12):
        found = nodes(text)
        if found:
            return found[0]
        time.sleep(0.3)
    return find(text)


def fill(index: int, value: str):
    for _ in range(5):
        scroll(True)
    fields = [
        n for n in dump().iter("node") if n.get("class") == "android.widget.EditText"
    ]
    tap(fields[index])
    adb("shell", "input", "keyevent", "123")
    adb(
        "shell",
        "input",
        "keyevent",
        *(["67"] * (len(fields[index].get("text", "")) + 2)),
    )
    adb("shell", "input", "text", value)
    adb("shell", "input", "keyevent", "4")


def save():
    tap(find("Сохранить и проверить"))


def main():
    # Не запускать на физическом устройстве и не использовать рабочий Core.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    response = opener.open(
        urllib.request.Request(
            URL + "notifications", headers={"Authorization": f"Bearer {API_KEY}"}
        )
    )
    assert json.load(response)["total"] == 0, "Нужен свежий изолированный Core-стенд"
    assert adb("shell", "getprop", "ro.kernel.qemu").strip() == "1"
    adb("reverse", "tcp:8000", "tcp:8000")
    adb("logcat", "-c")
    adb("shell", "am", "force-stop", PACKAGE)
    adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
    fill(0, URL)
    fill(1, API_KEY)
    save()
    find("Ключ принят")
    find("Не настроен")
    tap(find("Отправить тестовое уведомление"))
    for _ in range(4):
        scroll(True)
    find("Тест сохранён в Core: #1")
    response = opener.open(
        urllib.request.Request(
            URL + "notifications", headers={"Authorization": f"Bearer {API_KEY}"}
        )
    )
    data = json.load(response)
    assert (
        data["total"] == 1 and data["items"][0]["title"] == "Проверка подключения Shade"
    )
    prefs = adb("exec-out", "run-as", PACKAGE, "cat", "shared_prefs/shade_prefs.xml")
    assert API_KEY not in prefs and "api_key_cipher_v1" in prefs
    adb("shell", "am", "force-stop", PACKAGE)
    adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
    assert nodes(URL), "Адрес должен сохраниться после остановки процесса"
    save()
    find("Ключ принят")
    fill(1, WRONG_KEY)
    save()
    find("Ключ не принят")
    find("Не настроен")
    fill(0, "invalid-url")
    save()
    find("Укажите http:// или https://")
    fill(0, "http://127.0.0.2:8000")
    save()
    find("HTTP для этого адреса запрещён")
    fill(0, "http://127.0.0.1:8001")
    save()
    find("Введите ключ для этого адреса Core")
    fill(1, API_KEY)
    save()
    find("Нет соединения с Core")
    fill(0, URL)
    fill(1, API_KEY)
    save()
    find("Ключ принят")
    output = ROOT / "android/.gradle/task09-checks"
    output.mkdir(exist_ok=True)
    with (output / "emulator.png").open("wb") as image:
        subprocess.run(
            [str(ADB), "-s", "emulator-5554", "exec-out", "screencap", "-p"],
            stdout=image,
            check=True,
        )
    logs = adb("logcat", "-d")
    assert API_KEY not in logs and WRONG_KEY not in logs, (
        "Ключ не должен появляться в logcat"
    )
    assert "FATAL EXCEPTION" not in adb("logcat", "-b", "crash", "-d")
    tap(find("Удалить ключ", True))
    find("Ключ удалён с устройства", True)
    assert "api_key_cipher_v1" not in adb(
        "exec-out", "run-as", PACKAGE, "cat", "shared_prefs/shade_prefs.xml"
    )
    adb("shell", "am", "force-stop", PACKAGE)
    adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
    assert not nodes("Ключ сохранён."), "Удаление должно сохраниться после рестарта"
    adb("shell", "rm", "/sdcard/task09-ui.xml")
    print(
        "PASS: сохранение адреса/зашифрованного ключа, Bearer POST в Core, restart, 401/HA, URL/HTTP policy, привязка к адресу, удаление, отсутствие ключа в logcat"
    )


if __name__ == "__main__":
    main()
