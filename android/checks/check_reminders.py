"""TASK-24: UI и настоящие alarms/notifications только на read-only emulator-5554."""

import hashlib
import json
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from check_emulator import PACKAGE, adb, dump, fill, find, save, tap
from reminder_server import API_KEY

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:8002"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(path, post=False):
    with opener.open(
        urllib.request.Request(BASE + path, method="POST" if post else "GET"), timeout=5
    ) as response:
        return json.load(response)


def prefs():
    xml = ET.fromstring(
        adb(
            "exec-out",
            "run-as",
            PACKAGE,
            "cat",
            "shared_prefs/shade_calendar_reminders.xml",
        )
    )
    return {n.attrib["name"]: n.text for n in xml}


def until(predicate, seconds=50):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(1)
    raise AssertionError("Условие не выполнено в пределах времени")


def notifications():
    text = adb("shell", "dumpsys", "notification", "--noredact")
    return len(
        [
            line
            for line in text.splitlines()
            if "NotificationRecord(" in line
            and "pkg=com.shadeai.app" in line
            and "tag=shade-reminder:" in line
        ]
    )


def refresh():
    tap(find("Обновить расписание"))


def main():
    assert adb("shell", "getprop", "ro.kernel.qemu").strip() == "1", (
        "Только синтетический эмулятор"
    )
    assert (
        "read-only"
        in (
            ROOT / "android/.gradle/avd/ShadeTask03API35.avd/emu-launch-params.txt"
        ).read_text()
    ), "Требуется одноразовый read-only AVD"
    apk = ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"
    adb("install", "-r", str(apk))
    adb("shell", "pm", "clear", PACKAGE)
    adb("reverse", "tcp:8002", "tcp:8002")
    try:
        adb("shell", "appops", "set", PACKAGE, "SCHEDULE_EXACT_ALARM", "deny")
        adb("shell", "pm", "grant", PACKAGE, "android.permission.POST_NOTIFICATIONS")
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        fill(0, BASE + "/api/v1/")
        fill(1, API_KEY)
        save()
        find("Ключ принят")
        tap(find("Локальный календарь", True))
        find("Нужен системный доступ к точным будильникам")
        adb("shell", "appops", "set", PACKAGE, "SCHEDULE_EXACT_ALARM", "allow")
        adb("shell", "am", "force-stop", PACKAGE)
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        tap(find("Локальный календарь", True))
        find("Выключены")
        switches = [
            n
            for n in dump().iter("node")
            if n.get("checkable") == "true"
            and n.get("class") != "android.widget.CheckBox"
        ]
        assert len(switches) == 1 and switches[0].get("checked") == "false"
        print("PASS: exact-permission gate; включение opt-in", flush=True)
        tap(switches[0])
        until(lambda: prefs().get("source") == "a" * 64)
        normal = api("/checks/arm?seconds=35", True)
        refresh()
        until(lambda: normal["id"] in (prefs().get("items") or ""))
        assert "com.shadeai.app.CALENDAR_ALARM" in adb("shell", "dumpsys", "alarm"), (
            "AlarmManager не содержит PendingIntent"
        )
        adb("shell", "input", "keyevent", "3")
        until(lambda: notifications() == 1, 55)
        normal_delay_ms = round(
            (
                datetime.now(UTC)
                - datetime.fromisoformat(normal["due_at"].replace("Z", "+00:00"))
            ).total_seconds()
            * 1000
        )
        until(lambda: "receipts" in prefs())
        print("PASS: AlarmManager background notification", flush=True)
        first = api("/checks/state")["validation"]
        assert first >= 1
        # Повторная сверка того же события не создаёт ещё одно уведомление.
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        tap(find("Локальный календарь", True))
        refresh()
        time.sleep(3)
        assert notifications() == 1
        print("PASS: receipt suppresses repeat", flush=True)
        cancelled = api("/checks/arm?seconds=30", True)
        refresh()
        until(lambda: cancelled["id"] in (prefs().get("items") or ""))
        api("/checks/cancel", True)
        adb("shell", "input", "keyevent", "3")
        until(lambda: api("/checks/state")["validation"] > first, 45)
        assert notifications() == 1, "Отменённое событие напомнилось"
        # Force-stop снимает alarms; явный новый запуск восстанавливает расписание.
        print("PASS: cancelled event skipped", flush=True)
        restart = api("/checks/arm?seconds=45", True)
        adb("shell", "am", "force-stop", PACKAGE)
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        until(lambda: restart["id"] in (prefs().get("items") or ""))
        adb("shell", "input", "keyevent", "3")
        until(lambda: notifications() == 1, 65)
        assert (
            len(
                ET.fromstring(
                    adb(
                        "exec-out",
                        "run-as",
                        PACKAGE,
                        "cat",
                        "shared_prefs/shade_calendar_reminders.xml",
                    )
                ).find("set[@name='receipts']")
            )
            >= 2
        )
        # UI согласия/ack проверяется отдельно от фактической HA-команды.
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        tap(find("Локальный календарь", True))
        tap(find("Режим дома для встречи"))
        find("switch.dnd")
        # Выбираем checkbox в видимой строке устройства.
        row = [
            n
            for n in dump().iter("node")
            if n.get("checkable") == "true"
            and n.get("class") == "android.widget.CheckBox"
        ]
        assert row
        tap(row[0])
        tap(find("Подтверждаю выбранный режим"))
        until(lambda: api("/checks/state")["decisions"] == 1)
        find("Согласие сохранено")
        find("Я проверил устройство")
        checks = [
            n
            for n in dump().iter("node")
            if n.get("class") == "android.widget.CheckBox"
            and n.get("checked") == "false"
        ]
        assert checks
        tap(checks[-1])
        tap(find("Закрыть неопределённый результат"))
        until(lambda: api("/checks/state")["acks"] == 1)
        find("Обработка завершена")
        raw = adb(
            "exec-out",
            "run-as",
            PACKAGE,
            "cat",
            "shared_prefs/shade_calendar_reminders.xml",
        )
        assert API_KEY not in raw and "Синтетическая встреча" not in raw
        report = dict(
            result="PASS",
            apk_sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),
            normal_delay_ms=normal_delay_ms,
            api_level=int(adb("shell", "getprop", "ro.build.version.sdk").strip()),
            read_only_avd=True,
            permissions_granted_by_adb=True,
            boot_recovery_checked=False,
            synthetic_api=True,
            physical_phone=False,
            pi=False,
            doze_checked=False,
            checks=[
                "exact permission gate",
                "explicit opt-in",
                "AlarmManager background delivery",
                "validate before show",
                "same-time receipt suppresses repeat",
                "cancelled event skipped",
                "force-stop then explicit launch recovers",
                "meeting explicit targets",
                "checked ack serialized",
                "prefs no key or calendar text",
            ],
            validations=api("/checks/state")["validation"],
            notifications=notifications(),
        )
        (ROOT / "docs/reports/task-24-android-emulator.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        print(json.dumps(report, ensure_ascii=False))
    finally:
        adb("shell", "am", "force-stop", PACKAGE)
        adb("reverse", "--remove", "tcp:8002")
        adb("shell", "rm", "-f", "/sdcard/task09-ui.xml")


if __name__ == "__main__":
    main()
