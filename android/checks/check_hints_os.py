"""TASK-21: настоящий WorkManager/NotificationManager + Core feed, только read-only AVD."""

import hashlib
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from check_access import fill_settings
from check_emulator import PACKAGE, adb, dump, find, tap
from check_results_os import BASE, api
from results_server import API_KEY, PRIVATE, TEXT

ROOT = Path(__file__).resolve().parents[2]


def prefs():
    files = adb("exec-out", "run-as", PACKAGE, "ls", "shared_prefs")
    if "shade_local_hints.xml" not in files:
        return {}
    xml = ET.fromstring(
        adb("exec-out", "run-as", PACKAGE, "cat", "shared_prefs/shade_local_hints.xml")
    )
    return {node.get("name"): node.get("value", node.text) for node in xml}


def until(predicate, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(1)
    raise AssertionError("Условие OS21 не выполнено вовремя")


def notifications():
    data = adb("shell", "dumpsys", "notification", "--noredact")
    assert TEXT not in data and PRIVATE not in data and API_KEY not in data
    return len(
        [
            line
            for line in data.splitlines()
            if "NotificationRecord(" in line
            and "pkg=" + PACKAGE in line
            and "tag=shade-hint:" in line
        ]
    )


def toggle():
    find("Локальные подсказки")
    switches = [
        node
        for node in dump().iter("node")
        if node.get("checkable") == "true" and node.get("class") != "android.widget.CheckBox"
    ]
    assert len(switches) == 1
    tap(switches[0])


def check_now():
    tap(find("Проверить подсказки"))


def main():
    output = ROOT / "docs/reports/task-21-android-os.json"
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
    adb("shell", "pm", "revoke", PACKAGE, "android.permission.POST_NOTIFICATIONS")
    adb(
        "shell",
        "pm",
        "clear-permission-flags",
        PACKAGE,
        "android.permission.POST_NOTIFICATIONS",
        "user-set",
        "user-fixed",
    )
    adb("logcat", "-b", "crash", "-c")
    adb("reverse", "tcp:8003", "tcp:8003")
    try:
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        fill_settings(BASE + "/api/v1/", API_KEY)
        find("Ключ принят")
        tap(find("Сценарии и подсказки", True))
        find("Системные подсказки выключены")
        assert not prefs().get("enabled_revision") and notifications() == 0
        toggle()
        dialog = dump()
        deny = [
            node
            for node in dialog.iter("node")
            if node.get("text", "").casefold() in {"don't allow", "don’t allow", "не разрешать"}
        ]
        assert len(deny) == 1, "Нужен настоящий системный запрос POST_NOTIFICATIONS"
        tap(deny[0])
        find("Android не разрешил системные уведомления.")
        assert not prefs().get("enabled_revision") and notifications() == 0
        print("PASS: default-off/настоящий permission deny", flush=True)
        adb("shell", "pm", "grant", PACKAGE, "android.permission.POST_NOTIFICATIONS")
        toggle()
        until(lambda: prefs().get("cursor") == "1")
        assert notifications() == 0, "История при первом opt-in переиграна"
        api("/checks/hints/add", {})
        api("/checks/hints/delay/3", {})
        check_now()
        adb("shell", "input", "keyevent", "3")
        until(lambda: prefs().get("cursor") == "2" and notifications() == 1)
        activity = adb("shell", "dumpsys", "activity", "activities")
        resumed = [line for line in activity.splitlines() if "topResumedActivity=" in line]
        assert all(PACKAGE not in line for line in resumed)
        api("/checks/hints/delay/0", {})
        print("PASS: настоящий WorkManager→Core→системное уведомление в фоне", flush=True)
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        check_now()
        time.sleep(3)
        assert prefs().get("cursor") == "2" and notifications() == 1
        identity = prefs().get("feed")
        adb("shell", "am", "force-stop", PACKAGE)
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        tap(find("Сценарии и подсказки", True))
        find("Новые подсказки включены")
        baseline = notifications()
        check_now()
        time.sleep(3)
        assert prefs().get("cursor") == "2" and prefs().get("feed") == identity
        assert notifications() == baseline
        api("/checks/hints/rotate", {})
        check_now()
        until(lambda: prefs().get("feed") != identity)
        assert notifications() == baseline
        api("/checks/hints/add?kind=new_kind", {})
        check_now()
        until(lambda: prefs().get("cursor") == "3")
        assert notifications() == baseline
        print("PASS: repeat/restart/feed-reset/unknown-kind без переигрывания", flush=True)
        api("/checks/hints/add", {})
        api("/checks/hints/mode/denied", {})
        check_now()
        until(lambda: prefs().get("pause") == "access")
        assert prefs().get("cursor") == "3" and notifications() == baseline
        api("/checks/hints/mode/normal", {})
        check_now()
        until(lambda: prefs().get("cursor") == "4" and notifications() == baseline + 1)
        assert not prefs().get("pause")
        toggle()
        until(lambda: not prefs().get("enabled_revision") and notifications() == 0)
        api("/checks/hints/add", {})
        time.sleep(3)
        assert notifications() == 0
        # Новый revision настроек не переносит разрешение старого Core.
        toggle()
        until(lambda: prefs().get("cursor") == "5")
        tap(find("К подключению", True))
        fill_settings(BASE + "/api/v1/", API_KEY)
        find("Ключ принят")
        tap(find("Сценарии и подсказки", True))
        find("Системные подсказки выключены")
        api("/checks/hints/add", {})
        time.sleep(3)
        assert notifications() == 0
        data = json.dumps(prefs())
        assert API_KEY not in data and TEXT not in data and PRIVATE not in data
        assert api("/checks/state")["commands"] == 0
        assert "FATAL EXCEPTION" not in adb("logcat", "-b", "crash", "-d")
        result = dict(
            result="PASS",
            apk_sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),
            api_level=35,
            read_only_avd=True,
            actual_core=True,
            actual_workmanager=True,
            actual_notificationmanager=True,
            synthetic_hint_feed=True,
            native_llm=False,
            physical_phone=False,
            doze=False,
            periodic_15min=False,
            ha_commands=0,
            checks=[
                "default-off",
                "POST_NOTIFICATIONS deny",
                "explicit opt-in/baseline",
                "background notification/generic text",
                "repeat",
                "restart cursor",
                "feed reset",
                "unknown kind",
                "401 pause/explicit resume",
                "disable cancels",
                "revision opt-in",
                "prefs no source/key",
                "no app crash",
            ],
        )
        output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
    finally:
        adb("shell", "am", "force-stop", PACKAGE)
        adb("reverse", "--remove", "tcp:8003")
        adb("shell", "rm", "-f", "/sdcard/task09-ui.xml")


if __name__ == "__main__":
    main()
