"""TASK-13: синтетические NotificationListener → журнал → Core/SQLite. Только одноразовый AVD."""

import json
import sqlite3
import subprocess
import time
from datetime import datetime

import check_buffer
from check_buffer import core_items, publish, snapshot
from check_delivery import wait_for
from check_emulator import (
    ADB,
    API_KEY,
    PACKAGE,
    ROOT,
    adb,
    dump,
    fill,
    find,
    save,
    scroll,
    tap,
)
from check_sources import ALLOWED, COMPONENT, checked, sources_screen

ARTIFACTS = ROOT / "android/.gradle/task13-checks"
check_buffer.ARTIFACTS = ARTIFACTS / "snapshot"
ANDROID_URL = "http://10.0.2.2:8000/api/v1/"


def open_journal():
    adb(
        "shell",
        "am",
        "start",
        "-W",
        "-n",
        PACKAGE + "/.MainActivity",
        "-f",
        "0x34000000",
    )
    for _ in range(3):
        scroll(True)
    texts = [n.get("text", "") for n in dump().iter("node")]
    if "НА ЭТОМ УСТРОЙСТВЕ" not in texts:
        if "К подключению" in texts:
            tap(find("К подключению"))
        tap(find("Журнал уведомлений", top=True))
    find("НА ЭТОМ УСТРОЙСТВЕ", top=True)


def journal_sources():
    open_journal()
    tap(find("Источники", top=True))
    find("Доступ Android")


def shot(name):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    result = subprocess.check_output(
        [str(ADB), "-s", "emulator-5554", "exec-out", "screencap", "-p"]
    )
    (ARTIFACTS / name).write_bytes(result)


def core_sql(row):
    paths = list((ROOT / "core/.pytest_cache").glob("task09-emulator-*/emulator.db"))
    assert len(paths) == 1, "Нужен единственный изолированный Core"
    with sqlite3.connect(f"file:{paths[0]}?mode=ro", uri=True) as db:
        stored = db.execute(
            "SELECT id, title, text, timestamp FROM notifications_raw WHERE dedupe_key = ?",
            ("event:" + row["eventId"],),
        ).fetchone()
        assert stored is not None
        assert (stored[1], stored[2]) == (row["title"], row["text"])
        timestamp = datetime.fromisoformat(stored[3].replace("Z", "+00:00"))
        assert int(timestamp.timestamp() * 1000) == row["postTime"]
        return stored[0]


def main():
    assert adb("shell", "getprop", "ro.kernel.qemu").strip() == "1"
    assert not core_items(), "Нужен свежий checks/core_server.py"
    assert not adb("shell", "pm", "list", "packages", ALLOWED).strip(), (
        "Не заменяем установленное приложение"
    )
    apk = next(
        (ROOT / "android/checks/publisher/build/outputs/apk/allowed/debug").glob(
            "*.apk"
        )
    )
    installed = False
    try:
        adb("install", str(apk))
        installed = True
        adb("shell", "pm", "grant", ALLOWED, "android.permission.POST_NOTIFICATIONS")
        adb(
            "install",
            "-r",
            str(ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"),
        )
        adb("shell", "cmd", "notification", "disallow_listener", COMPONENT)
        adb("shell", "pm", "clear", PACKAGE)
        adb("shell", "svc", "wifi", "enable")
        adb("shell", "svc", "data", "enable")
        adb("logcat", "-c")
        open_journal()
        find("Здесь пока нет записей")
        shot("journal-empty.png")
        tap(find("К подключению", top=True))
        fill(0, ANDROID_URL)
        fill(1, API_KEY)
        save()
        find("Ключ принят")
        sources_screen()
        tap(find("Ozon"))
        assert checked("Ozon")
        adb("shell", "cmd", "notification", "allow_listener", COMPONENT)
        time.sleep(1)
        adb("shell", "svc", "wifi", "disable")
        adb("shell", "svc", "data", "disable")
        time.sleep(1)
        publish("big", 71)
        first = wait_for(
            lambda r: len(r) == 1 and r[0]["status"] == "PENDING", "Нет офлайн-записи"
        )[0]
        open_journal()
        find("Ожидает отправки")
        find(first["title"])
        shot("journal-pending.png")
        tap(find(first["title"]))
        find("UUID: " + first["eventId"])
        tap(find("Закрыть запись"))
        assert not core_items()
        print(
            "PASS: пустой журнал → реальный listener → PENDING/полный текст/UUID без сети",
            flush=True,
        )

        adb("shell", "svc", "wifi", "enable")
        sent = wait_for(
            lambda r: len(r) == 1 and r[0]["status"] == "SENT", "Нет подтверждения"
        )[0]
        find("Получено Core", top=True)
        for _ in range(3):
            scroll(True)
        shot("journal-sent.png")
        core_id = core_sql(sent)
        api_row = core_items()[0]
        assert api_row["event_id"] == first["eventId"] and api_row["id"] == core_id
        (ARTIFACTS / "event.json").write_text(
            json.dumps(
                {
                    "uuid": sent["eventId"],
                    "id": core_id,
                    "title": sent["title"],
                    "text": sent["text"],
                    "timestamp": api_row["timestamp"],
                },
                ensure_ascii=False,
            )
        )
        publish("big", 71)
        assert len(snapshot()) == 1 and len(core_items()) == 1
        adb("shell", "am", "force-stop", PACKAGE)
        open_journal()
        find("Получено Core")
        assert snapshot()[0]["eventId"] == first["eventId"]
        print(
            "PASS: SENT обновился в UI; UUID/текст/время совпадают с Core SQLite/API; повтор/restart без дубля",
            flush=True,
        )

        adb("shell", "input", "keyevent", "223")
        time.sleep(1)
        publish("inbox", 72)
        wait_for(
            lambda r: len(r) == 2 and r[-1]["status"] == "SENT",
            "Нет доставки при выключенном экране",
        )
        assert "mWakefulness=Asleep" in adb("shell", "dumpsys", "power")
        adb("shell", "input", "keyevent", "224")
        adb("shell", "wm", "dismiss-keyguard")
        open_journal()
        find("Синтетическая доставка inbox")
        assert len(core_items()) == 2
        print(
            "PASS: доставка при Asleep на AOSP API 35; после пробуждения журнал показывает обе записи",
            flush=True,
        )

        journal_sources()
        tap(find("Ozon"))
        assert not checked("Ozon")
        wait_for(lambda r: len(r) == 0, "Источник не удалён")
        open_journal()
        find("Здесь пока нет записей")
        assert len(core_items()) == 2
        journal_sources()
        tap(find("Ozon"))
        assert checked("Ozon")
        adb("shell", "svc", "wifi", "disable")
        adb("shell", "svc", "data", "disable")
        time.sleep(1)
        publish("ticker", 73)
        wait_for(lambda r: len(r) == 1, "Нет записи до отзыва доступа")
        open_journal()
        find("Ожидает отправки")
        adb("shell", "cmd", "notification", "disallow_listener", COMPONENT)
        tap(find("Обновить журнал", top=True))
        wait_for(lambda r: len(r) == 0, "Буфер не очищен после отзыва")
        find("Здесь пока нет записей")
        assert len(core_items()) == 2
        print(
            "PASS: выключение источника/отзыв доступа очищают журнал; Core сохраняет свою копию",
            flush=True,
        )
        logs = adb("logcat", "-d")
        assert "FATAL EXCEPTION" not in logs and API_KEY not in logs
    finally:
        adb("shell", "input", "keyevent", "224")
        adb("shell", "wm", "dismiss-keyguard")
        adb("shell", "svc", "wifi", "enable")
        adb("shell", "svc", "data", "enable")
        adb("shell", "cmd", "notification", "disallow_listener", COMPONENT)
        if installed:
            adb("uninstall", ALLOWED)
        adb("shell", "rm", "-f", "/sdcard/task09-ui.xml")


if __name__ == "__main__":
    main()
