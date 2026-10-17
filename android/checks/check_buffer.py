"""TASK-11: синтетический системный перехват → офлайн Room → restart → Core; только AVD."""

import json
import sqlite3
import subprocess
import time
import urllib.request
from datetime import UTC, datetime
from uuid import UUID

from check_emulator import ADB, API_KEY, PACKAGE, ROOT, URL, adb, fill, find, save, tap
from check_sources import ALLOWED, COMPONENT, OPENER, checked, sources_screen

ARTIFACTS = ROOT / "android/.gradle/task11-checks/snapshot"


def core_items():
    with OPENER.open(
        urllib.request.Request(
            URL + "notifications?limit=100",
            headers={"Authorization": "Bearer " + API_KEY},
        ),
        timeout=5,
    ) as response:
        return json.load(response)["items"]


def snapshot():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    for name in ("shade.db", "shade.db-wal", "shade.db-shm"):
        path = ARTIFACTS / name
        path.unlink(missing_ok=True)
        result = subprocess.run(
            [
                str(ADB),
                "-s",
                "emulator-5554",
                "exec-out",
                "run-as",
                PACKAGE,
                "cat",
                "databases/" + name,
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            path.write_bytes(result.stdout)
    with sqlite3.connect(ARTIFACTS / "shade.db") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        db.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in db.execute("SELECT * FROM pending_notifications ORDER BY id")
        ]


def wait_rows(count, status=None):
    for _ in range(40):
        rows = snapshot()
        if len(rows) == count and (
            status is None or all(row["status"] == status for row in rows)
        ):
            return rows
        time.sleep(0.25)
    raise AssertionError(
        f"Room: нужно {count}/{status}, получено {[(r['id'], r['status']) for r in rows]}"
    )


def publish(kind, identifier, variant="original"):
    adb(
        "shell",
        "am",
        "start",
        "-W",
        "-n",
        ALLOWED + "/com.shadeai.fixture.PublisherActivity",
        "--es",
        "kind",
        kind,
        "--es",
        "variant",
        variant,
        "--ei",
        "id",
        str(identifier),
    )
    time.sleep(0.6)


def reconnect():
    adb("shell", "cmd", "notification", "disallow_listener", COMPONENT)
    adb("shell", "cmd", "notification", "allow_listener", COMPONENT)
    time.sleep(0.7)


def main():
    assert adb("shell", "getprop", "ro.kernel.qemu").strip() == "1", "Нужен эмулятор"
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
        adb("reverse", "tcp:8000", "tcp:8000")
        adb("logcat", "-c")
        adb("shell", "am", "start", "-W", "-n", PACKAGE + "/.MainActivity")
        fill(0, URL)
        fill(1, API_KEY)
        save()
        find("Ключ принят")
        sources_screen()
        assert not checked("Ozon")
        tap(find("Ozon"))
        assert checked("Ozon")
        adb("reverse", "--remove", "tcp:8000")
        adb("shell", "cmd", "notification", "allow_listener", COMPONENT)
        time.sleep(0.7)
        print("PASS: чистая настройка, выбран Ozon, сеть Core отключена", flush=True)

        publish("big", 41)
        first = wait_rows(1, "FAILED")[0]
        assert first["text"] == "Курьер в пути. Доставка ожидается вечером"
        UUID(first["eventId"])
        publish("big", 41)
        assert wait_rows(1) == [first]
        publish("big", 41, "updated")
        changed = wait_rows(2)[-1]
        assert changed["text"] == "Курьер подъезжает. Доставка скоро прибудет"
        assert changed["eventId"] != first["eventId"]
        print(
            "PASS: BigText сохраняется без сети, повтор не создаёт строку, обновление имеет новый UUID",
            flush=True,
        )

        publish("inbox", 42)
        assert wait_rows(3)[-1]["text"] == "Заказ принят\nПередан курьеру"
        publish("ticker", 43)
        assert wait_rows(4)[-1]["text"] == "Синтетическая доставка готова"
        publish("title-only", 44)
        assert wait_rows(5)[-1]["text"] == ""
        for i, kind in enumerate(
            ("hidden-sensitive", "ongoing", "local", "summary"), 45
        ):
            publish(kind, i)
            assert len(snapshot()) == 5
        before = wait_rows(5, "FAILED")
        assert not core_items()
        print(
            "PASS: Inbox/ticker/без text; скрытый код и служебные уведомления не попали в Room/Core",
            flush=True,
        )

        adb("shell", "am", "force-stop", PACKAGE)
        assert snapshot() == before
        adb("shell", "am", "start", "-W", "-n", PACKAGE + "/.MainActivity")
        reconnect()
        assert wait_rows(5, "FAILED") == before
        publish("big", 41, "updated")
        assert wait_rows(5) == before
        publish("cancel", 41)
        time.sleep(0.5)
        publish("big", 41, "updated")
        reposted = wait_rows(6)[-1]
        assert reposted["eventId"] != changed["eventId"]
        print(
            "PASS: force-stop сохраняет payload/UUID/статусы; повтор после rebind пропущен, cancel/repost — новая запись",
            flush=True,
        )

        adb("reverse", "tcp:8000", "tcp:8000")
        reconnect()
        delivered = wait_rows(6, "SENT")
        items = core_items()
        assert len(items) == 6
        assert {item["event_id"] for item in items} == {
            row["eventId"] for row in delivered
        }
        by_uuid = {item["event_id"]: item for item in items}
        for row in delivered:
            stored = by_uuid[row["eventId"]]
            assert (stored["title"], stored["text"]) == (row["title"], row["text"])
            actual_time = datetime.fromisoformat(
                stored["timestamp"].replace("Z", "+00:00")
            )
            assert int(actual_time.timestamp() * 1000) == row["postTime"]
        publish("big", 41, "updated")
        assert wait_rows(6, "SENT") == delivered
        assert len(core_items()) == 6
        original = delivered[0]
        request = {
            "app_name": original["packageName"],
            "title": original["title"],
            "text": original["text"],
            "timestamp": datetime.fromtimestamp(
                original["postTime"] / 1000, UTC
            ).isoformat(),
            "event_id": original["eventId"],
        }
        with OPENER.open(
            urllib.request.Request(
                URL + "notifications",
                data=json.dumps(request).encode(),
                headers={
                    "Authorization": "Bearer " + API_KEY,
                    "Content-Type": "application/json",
                },
            ),
            timeout=5,
        ) as response:
            assert json.load(response)["status"] == "duplicate"
        assert len(core_items()) == 6
        print(
            "PASS: reconnect доставляет 6 сохранённых UUID/времён в Core; повтор payload даёт duplicate",
            flush=True,
        )

        assert "FATAL EXCEPTION" not in adb("logcat", "-b", "crash", "-d")
        logs = adb("logcat", "-d")
        assert API_KEY not in logs and "Код 1234" not in logs
        for path in ARTIFACTS.glob("shade.db*"):
            assert "Код 1234".encode() not in path.read_bytes()
        print(
            "TASK-11: все эмуляторные сценарии пройдены; телефон не проверялся",
            flush=True,
        )
    finally:
        if installed:
            adb("uninstall", ALLOWED)
        adb("shell", "cmd", "notification", "disallow_listener", COMPONENT)
        subprocess.run(
            [str(ADB), "-s", "emulator-5554", "reverse", "--remove", "tcp:8000"],
            capture_output=True,
            check=False,
        )
        adb("shell", "rm", "-f", "/sdcard/task09-ui.xml")


if __name__ == "__main__":
    main()
