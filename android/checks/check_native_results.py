"""TASK-19: реальный системный capture и показ той же записи после offline Core."""

import argparse
import hashlib
import json
import time
import urllib.request

from check_access import fill_settings
from check_emulator import PACKAGE, ROOT, adb, find, tap
from check_sources import ALLOWED, COMPONENT, checked, publish, sources_screen
from native_results_core import BASE, CONTROL_TITLE, KEY

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
APK = ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"
PUBLISHER = ROOT / (
    "android/checks/publisher/build/outputs/apk/allowed/debug/notification-publisher-allowed-debug.apk"
)


def items():
    request = urllib.request.Request(
        BASE + "/api/v1/notifications", headers={"Authorization": "Bearer " + KEY}
    )
    with OPENER.open(request, timeout=5) as response:
        return json.load(response)["items"]


def hash_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("capture", "display"))
    args = parser.parse_args()
    capture = args.phase == "capture"
    assert adb("shell", "getprop", "ro.kernel.qemu").strip() == "1"
    assert adb("shell", "getprop", "ro.build.version.sdk").strip() == "35"
    assert (
        "-read-only"
        in (
            ROOT / "android/.gradle/avd/ShadeTask03API35.avd/emu-launch-params.txt"
        ).read_text()
    )
    rows = items()
    if capture:
        assert not rows
    else:
        assert len(rows) in (2, 3)
        titles = {row["title"] for row in rows}
        assert titles in (
            {"Синтетическая доставка order", "Синтетическая доставка big"},
            {
                "Синтетическая доставка order",
                "Синтетическая доставка big",
                CONTROL_TITLE,
            },
        )
    assert not adb("shell", "pm", "list", "packages", ALLOWED).strip()
    adb("install", "-r", str(APK))
    adb("shell", "pm", "clear", PACKAGE)
    adb("logcat", "-b", "crash", "-c")
    adb("reverse", "tcp:8003", "tcp:8003")
    report = {"phase": args.phase, "apk_sha256": hash_file(APK), "hardware": False}
    try:
        adb("shell", "am", "start", "-W", "-n", PACKAGE + "/.MainActivity")
        fill_settings(BASE + "/api/v1/", KEY)
        find("Ключ принят")
        if capture:
            adb("install", str(PUBLISHER))
            adb(
                "shell", "pm", "grant", ALLOWED, "android.permission.POST_NOTIFICATIONS"
            )
            adb("shell", "cmd", "notification", "allow_listener", COMPONENT)
            sources_screen()
            find("Доступ Android выдан")
            assert not checked("Ozon")
            tap(find("Ozon"))
            assert checked("Ozon")
            publish("order", 11)
            publish("big", 12)
            for _ in range(90):
                rows = items()
                if len(rows) >= 2:
                    break
                time.sleep(1)
            assert len(rows) == 2 and all(
                row["processing_status"] == "pending" for row in rows
            )
            assert {row["title"] for row in rows} == {
                "Синтетическая доставка order",
                "Синтетическая доставка big",
            }
            assert len({row["event_id"] for row in rows if row["event_id"]}) == 2
            report["publisher_sha256"] = hash_file(PUBLISHER)
        else:
            assert {row["processing_status"] for row in rows} <= {"processed", "failed"}
            tap(find("Результаты Core", True))
            find(f"Всего: {len(rows)} · Страница 1")
            for index, row in enumerate(rows):
                if index:
                    tap(find("К списку результатов", True))
                tap(find(row["title"]))
                if row["processing_status"] == "processed":
                    find("Локальный разбор")
                    find("Asia/Yekaterinburg")
                else:
                    assert row["processing_error_code"] == "LLM_BAD_RESPONSE"
                    find("Модель вернула неподтверждённые или неполные сведения")
        assert "FATAL EXCEPTION" not in adb("logcat", "-b", "crash", "-d")
        report["rows"] = [
            {k: row[k] for k in ("id", "event_id", "processing_status")} for row in rows
        ]
        report["result"] = "PASS"
        print(json.dumps(report, ensure_ascii=False), flush=True)
    finally:
        adb("shell", "am", "force-stop", PACKAGE)
        adb("reverse", "--remove", "tcp:8003")
        adb("shell", "rm", "-f", "/sdcard/task09-ui.xml")


if __name__ == "__main__":
    main()
