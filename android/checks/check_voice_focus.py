"""AOSP35: потеря фокуса останавливает AudioRecord и не отправляет WAV в Core."""

import hashlib
import json
import time
from pathlib import Path

# Общие медленные жесты/настройка уже проверены в TASK-26; данные только синтетические.
from check_access import fill_settings
from check_emulator import PACKAGE, adb, dump, find, tap
from check_voice import api
from voice_server import API_KEY, TEXT

ROOT = Path(__file__).resolve().parents[2]


def main():
    output = ROOT / "docs/reports/voice-focus-2026-10-19.json"
    assert not output.exists()
    assert adb("shell", "getprop", "ro.kernel.qemu").strip() == "1"
    assert (
        "read-only"
        in (ROOT / "android/.gradle/avd/ShadeTask03API35.avd/emu-launch-params.txt").read_text()
    )
    assert api("/checks/state")["stt_calls"] == 0
    apk = ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"
    adb("install", "-r", str(apk))
    adb("shell", "pm", "clear", PACKAGE)
    adb("shell", "pm", "grant", PACKAGE, "android.permission.RECORD_AUDIO")
    adb("reverse", "tcp:8003", "tcp:8003")
    try:
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        fill_settings("http://127.0.0.1:8003/api/v1/", API_KEY)
        find("Ключ принят")
        tap(find("Голосовая команда", True))
        find("Записать команду")
        tap(find("Записать команду"))
        find("Идёт запись")
        adb("shell", "input", "keyevent", "187")
        time.sleep(1)
        audio_op = adb("shell", "cmd", "appops", "get", PACKAGE, "RECORD_AUDIO")
        assert "running" not in audio_op.lower(), "AudioRecord ещё активен после Overview"
        time.sleep(10)
        assert api("/checks/state")["stt_calls"] == 0, "Запись ушла в STT после Overview"
        assert api("/checks/state")["commands"] == 0
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        time.sleep(1)
        body = " ".join(node.get("text", "") for node in dump().iter("node"))
        assert "Идёт запись" not in body and "Распознано:" not in body
        # Возврат не начинает запись; новый явный ввод по кнопке ещё работает.
        tap(find("Записать команду", True))
        find("Идёт запись")
        time.sleep(1)
        tap(find("Готово — распознать"))
        find("Распознано: «" + TEXT + "»")
        assert api("/checks/state")["stt_calls"] == 1 and api("/checks/state")["commands"] == 0
        adb("shell", "input", "keyevent", "187")
        time.sleep(1)
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        time.sleep(1)
        body = " ".join(node.get("text", "") for node in dump().iter("node"))
        assert "Распознано:" not in body
        result = dict(
            result="PASS",
            apk_sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),
            api_level=35,
            read_only_avd=True,
            actual_audio_record=True,
            actual_core=True,
            native_stt=False,
            synthetic_stt=True,
            synthetic_ha=True,
            hardware=False,
            stt_calls=1,
            ha_commands=0,
            checks=[
                "Overview cancels recording before STT",
                "audio app-op not running after1s",
                "resume does not record",
                "new explicit recording works",
                "Overview clears transcript",
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
