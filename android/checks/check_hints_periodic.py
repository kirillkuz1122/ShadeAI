"""TASK-21: один настоящий период WorkManager без ускорения часов/job на AOSP35."""

import hashlib
import json
import time
from pathlib import Path

from check_access import fill_settings
from check_emulator import PACKAGE, adb, find, tap
from check_hints_os import notifications, prefs, toggle, until
from check_results_os import BASE, api
from results_server import API_KEY, PRIVATE, TEXT

ROOT = Path(__file__).resolve().parents[2]


def background():
    lines = adb("shell", "dumpsys", "activity", "activities").splitlines()
    resumed = [
        line for line in lines if "topResumedActivity=" in line or "mResumedActivity:" in line
    ]
    return bool(resumed) and all(PACKAGE not in line for line in resumed)


def main():
    output = ROOT / "docs/reports/task-21-periodic-android.json"
    assert not output.exists()
    assert adb("shell", "getprop", "ro.kernel.qemu").strip() == "1"
    assert (
        "read-only"
        in (ROOT / "android/.gradle/avd/ShadeTask03API35.avd/emu-launch-params.txt").read_text()
    )
    assert api("/checks/state")["hint_id"] == 1
    apk = ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"
    adb("install", "-r", str(apk))
    adb("shell", "pm", "clear", PACKAGE)
    adb("shell", "pm", "grant", PACKAGE, "android.permission.POST_NOTIFICATIONS")
    adb("logcat", "-b", "crash", "-c")
    adb("reverse", "tcp:8003", "tcp:8003")
    timeout_before = adb("shell", "settings", "get", "system", "screen_off_timeout").strip()
    try:
        adb("shell", "settings", "put", "system", "screen_off_timeout", "1800000")
        adb("shell", "input", "keyevent", "224")
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        fill_settings(BASE + "/api/v1/", API_KEY)
        find("Ключ принят")
        tap(find("Сценарии и подсказки", True))
        enabled = time.monotonic()
        toggle()
        until(lambda: prefs().get("cursor") == "1")
        adb("shell", "input", "keyevent", "3")
        assert background()
        # Opt-in автоматически создаёт NOW и периодическую работу. Ждём их baseline.
        time.sleep(30)
        reads = api("/checks/state")["hint_reads"]
        assert reads >= 1 and prefs().get("cursor") == "1" and notifications() == 0
        api("/checks/hints/add", {})
        queued = time.monotonic()
        next_progress = queued + 60
        while time.monotonic() - enabled < 1200:
            state = api("/checks/state")
            if notifications() == 1 and prefs().get("cursor") == "2":
                break
            if time.monotonic() >= next_progress:
                print(
                    json.dumps(
                        dict(
                            waited_seconds=round(time.monotonic() - enabled),
                            extra_hint_reads=state["hint_reads"] - reads,
                        )
                    ),
                    flush=True,
                )
                next_progress += 60
            time.sleep(5)
        else:
            raise AssertionError("Естественный период не доставил подсказку за 20 минут")
        elapsed = round(time.monotonic() - enabled, 3)
        assert elapsed >= 880, "Нельзя считать ранний запуск проверкой 15-минутного периода"
        assert background() and "mWakefulness=Awake" in adb("shell", "dumpsys", "power")
        state = api("/checks/state")
        assert state["hint_reads"] == reads + 1 and state["commands"] == 0
        time.sleep(10)
        assert notifications() == 1 and prefs().get("cursor") == "2"
        saved = adb("exec-out", "run-as", PACKAGE, "cat", "shared_prefs/shade_local_hints.xml")
        assert all(value not in saved for value in (API_KEY, TEXT, PRIVATE))
        assert "FATAL EXCEPTION" not in adb("logcat", "-b", "crash", "-d")
        result = dict(
            result="PASS",
            apk_sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),
            api_level=35,
            actual_core=True,
            actual_workmanager=True,
            actual_notificationmanager=True,
            real_periodic_15min=True,
            forced_job=False,
            clock_changed=False,
            activity_opened_after_optin=False,
            manual_check_now=False,
            initial_optin_baseline=True,
            observed_seconds_since_optin=elapsed,
            seconds_since_hint_at_final_check=round(time.monotonic() - queued, 3),
            synthetic_feed=True,
            native_llm=False,
            physical_phone=False,
            pi=False,
            doze=False,
            screen_awake=True,
            hint_reads_baseline=reads,
            hint_reads_final=state["hint_reads"],
            ha_commands=0,
            checks=[
                "natural periodic request",
                "background generic notification",
                "cursor receipt",
                "no repeat",
                "prefs privacy",
                "no app crash",
            ],
        )
        output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result), flush=True)
    finally:
        if timeout_before == "null":
            adb("shell", "settings", "delete", "system", "screen_off_timeout")
        else:
            adb("shell", "settings", "put", "system", "screen_off_timeout", timeout_before)
        adb("shell", "am", "force-stop", PACKAGE)
        adb("reverse", "--remove", "tcp:8003")
        adb("shell", "rm", "-f", "/sdcard/task09-ui.xml")


if __name__ == "__main__":
    main()
