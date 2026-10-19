"""TASK-24: alarm без сети → bounded retry после восстановления, только AVD."""

import hashlib
import json
import time
from pathlib import Path

from check_access import fill_settings
from check_emulator import PACKAGE, adb, dump, find, tap
from check_reminders import api, notifications, prefs, until
from reminder_server import API_KEY

ROOT = Path(__file__).resolve().parents[2]


def main():
    output = ROOT / "docs/reports/task-24-offline-os.json"
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
    try:
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        fill_settings("http://10.0.2.2:8002/api/v1/", API_KEY)
        find("Ключ принят")
        tap(find("Локальный календарь", True))
        find("Выключены")
        switches = [
            n
            for n in dump().iter("node")
            if n.get("checkable") == "true"
            and n.get("class") != "android.widget.CheckBox"
        ]
        assert len(switches) == 1
        tap(switches[0])
        until(lambda: prefs().get("source") == "a" * 64)
        pending = api("/checks/arm?seconds=35", True)
        tap(find("Обновить расписание"))
        until(lambda: pending["id"] in (prefs().get("items") or ""))
        adb("shell", "input", "keyevent", "3")
        adb("shell", "svc", "wifi", "disable")
        adb("shell", "svc", "data", "disable")
        started = time.monotonic()
        # Ждём за пределами due и HTTP timeout, не открывая Activity.
        time.sleep(48)
        assert notifications() == 0
        assert "receipts" not in prefs()
        assert api("/checks/state")["validation"] == 0
        jobs = adb("shell", "dumpsys", "jobscheduler")
        assert (
            PACKAGE + "/androidx.work.impl.background.systemjob.SystemJobService"
            in jobs
        )
        print(
            "PASS: без сети alarm не показал неподтверждённое событие; retry запланирован",
            flush=True,
        )
        adb("shell", "svc", "wifi", "enable")
        until(lambda: notifications() == 1, 100)
        until(lambda: "receipts" in prefs())
        assert api("/checks/state")["validation"] == 1
        elapsed = round(time.monotonic() - started, 3)
        time.sleep(3)
        assert notifications() == 1
        saved = adb(
            "exec-out",
            "run-as",
            PACKAGE,
            "cat",
            "shared_prefs/shade_calendar_reminders.xml",
        )
        assert (
            API_KEY not in saved
            and "http" not in saved
            and "Синтетическая встреча" not in saved
        )
        assert "FATAL EXCEPTION" not in adb("logcat", "-b", "crash", "-d")
        result = dict(
            result="PASS",
            apk_sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),
            api_level=35,
            read_only_avd=True,
            synthetic_api=True,
            actual_core=False,
            physical_phone=False,
            pi=False,
            native_model=False,
            forced_doze=False,
            activity_opened_for_recovery=False,
            offline_seconds=48,
            observation_elapsed_seconds=elapsed,
            checks=[
                "no unvalidated notification offline",
                "no receipt offline",
                "WorkManager scheduled job",
                "automatic recovery within grace",
                "one validation and notification",
                "prefs privacy",
                "no app crash",
            ],
        )
        output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result), flush=True)
    finally:
        adb("shell", "svc", "wifi", "enable")
        adb("shell", "svc", "data", "enable")
        adb("shell", "am", "force-stop", PACKAGE)
        adb("shell", "rm", "-f", "/sdcard/task09-ui.xml")


if __name__ == "__main__":
    main()
