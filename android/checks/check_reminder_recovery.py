"""TASK-24: настоящий reboot/forced Doze AOSP35, синтетический API, без телефона."""

import hashlib
import json
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from check_access import fill_settings
from check_emulator import PACKAGE, adb, dump, find, tap
from check_reminders import api, notifications, prefs, until
from reminder_server import API_KEY

ROOT = Path(__file__).resolve().parents[2]


def boot_id():
    return adb("shell", "cat", "/proc/sys/kernel/random/boot_id").strip()


def booted(previous):
    try:
        return (
            adb("shell", "getprop", "sys.boot_completed").strip() == "1"
            and boot_id() != previous
        )
    except subprocess.CalledProcessError:
        return False


def due_delay(item):
    return round(
        (
            datetime.now(UTC)
            - datetime.fromisoformat(item["due_at"].replace("Z", "+00:00"))
        ).total_seconds()
        * 1000
    )


def main():
    output = ROOT / "docs/reports/task-24-recovery-os.json"
    assert not output.exists()
    assert adb("shell", "getprop", "ro.kernel.qemu").strip() == "1"
    assert (
        "read-only"
        in (
            ROOT / "android/.gradle/avd/ShadeTask03API35.avd/emu-launch-params.txt"
        ).read_text()
    )
    assert api("/checks/state")["validation"] == 0
    apk = ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"
    adb("install", "-r", str(apk))
    adb("shell", "pm", "clear", PACKAGE)
    adb("logcat", "-b", "crash", "-c")
    adb("shell", "pm", "grant", PACKAGE, "android.permission.POST_NOTIFICATIONS")
    adb("shell", "appops", "set", PACKAGE, "SCHEDULE_EXACT_ALARM", "allow")
    initial_deep = adb("shell", "dumpsys", "deviceidle", "enabled", "deep").strip()
    try:
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        # 10.0.2.2 — host loopback alias; сеть остаётся доступна после reboot без adb reverse.
        fill_settings("http://10.0.2.2:8002/api/v1/", API_KEY)
        find("Ключ принят")
        tap(find("Локальный календарь", True))
        find("Выключены")
        switches = [
            node
            for node in dump().iter("node")
            if node.get("checkable") == "true"
            and node.get("class") != "android.widget.CheckBox"
        ]
        assert len(switches) == 1
        tap(switches[0])
        until(lambda: prefs().get("source") == "a" * 64)
        idle_item = api("/checks/arm?seconds=35", True)
        tap(find("Обновить расписание"))
        until(lambda: idle_item["id"] in (prefs().get("items") or ""))
        assert PACKAGE not in adb("shell", "dumpsys", "deviceidle", "whitelist")
        adb("shell", "input", "keyevent", "3")
        adb("shell", "dumpsys", "battery", "unplug")
        adb("shell", "input", "keyevent", "223")
        # AVD по умолчанию отключает Doze: включаем только в одноразовом стенде.
        adb("shell", "dumpsys", "deviceidle", "enable", "deep")
        assert adb("shell", "dumpsys", "deviceidle", "enabled", "deep").strip() == "1"
        reply = adb("shell", "dumpsys", "deviceidle", "force-idle", "deep")
        assert "IDLE" in adb("shell", "dumpsys", "deviceidle", "get", "deep").upper(), (
            reply
        )
        until(lambda: notifications() == 1, 100)
        idle_delay = due_delay(idle_item)
        until(lambda: "receipts" in prefs())
        print("PASS: первый exact alarm в forced deep idle, без whitelist", flush=True)
        adb("shell", "dumpsys", "deviceidle", "unforce")
        adb("shell", "dumpsys", "battery", "reset")
        adb("shell", "input", "keyevent", "224")
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        tap(find("Локальный календарь", True))
        tap(find("Обновить расписание"))
        time.sleep(3)
        assert notifications() == 1
        pending = api("/checks/arm?seconds=120", True)
        tap(find("Обновить расписание"))
        until(lambda: pending["id"] in (prefs().get("items") or ""))
        adb("shell", "input", "keyevent", "3")
        previous = boot_id()
        reads = api("/checks/state")["schedule_reads"]
        adb("reboot")
        until(lambda: booted(previous), 100)
        adb("shell", "input", "keyevent", "82")
        # Не открываем Activity и не посылаем поддельный BOOT_COMPLETED.
        until(lambda: api("/checks/state")["schedule_reads"] > reads, 45)
        until(
            lambda: (
                "com.shadeai.app.CALENDAR_ALARM" in adb("shell", "dumpsys", "alarm")
            ),
            30,
        )
        until(lambda: notifications() == 1, 140)
        reboot_delay = due_delay(pending)
        until(
            lambda: (
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
        )
        print(
            "PASS: reboot→автовосстановление alarm→уведомление без Activity", flush=True
        )
        data = adb(
            "exec-out",
            "run-as",
            PACKAGE,
            "cat",
            "shared_prefs/shade_calendar_reminders.xml",
        )
        assert (
            API_KEY not in data
            and "Синтетическая встреча" not in data
            and "http" not in data
        )
        assert "FATAL EXCEPTION" not in adb("logcat", "-b", "crash", "-d")
        result = dict(
            result="PASS",
            apk_sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),
            api_level=35,
            read_only_avd=True,
            actual_reboot=True,
            actual_alarmmanager=True,
            activity_not_opened_for_boot_recovery=True,
            forced_doze=True,
            deep_idle_initially_enabled=initial_deep == "1",
            deep_idle_enabled_by_test=True,
            permanent_whitelist=False,
            synthetic_api=True,
            actual_core=False,
            physical_phone=False,
            pi=False,
            native_model=False,
            reboot_delay_ms=reboot_delay,
            forced_idle_delay_ms=idle_delay,
            checks=[
                "boot id changed",
                "recovery GET before Activity",
                "alarm restored after reboot",
                "validated background show",
                "receipt suppresses repeat",
                "forced deep idle delivery",
                "prefs privacy",
                "no app crash",
            ],
        )
        output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
    finally:
        adb("shell", "dumpsys", "deviceidle", "unforce")
        if initial_deep == "0":
            adb("shell", "dumpsys", "deviceidle", "disable", "deep")
        adb("shell", "dumpsys", "battery", "reset")
        adb("shell", "input", "keyevent", "224")
        adb("shell", "am", "force-stop", PACKAGE)
        adb("shell", "rm", "-f", "/sdcard/task09-ui.xml")


if __name__ == "__main__":
    main()
