"""AudioRecord→WAV→настоящий Core, синтетические STT/HA; только read-only AVD."""

import hashlib
import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path

from check_emulator import PACKAGE, adb, dump, find, nodes, scroll, tap
from voice_server import API_KEY, TEXT

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:8003"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(path, post=False):
    with opener.open(
        urllib.request.Request(BASE + path, method="POST" if post else "GET"), timeout=5
    ) as response:
        return json.load(response)


def until(predicate, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        result = predicate()
        if result:
            return result
        time.sleep(0.5)
    raise AssertionError("Условие не выполнено")


def open_voice():
    tap(find("Голосовая команда", True))


def record():
    tap(find("Записать команду", True))
    find("Идёт запись")
    time.sleep(1)
    tap(find("Готово — распознать", True))
    find("Распознано: «" + TEXT + "»")


def fill_settings(url, key):
    # Новые навигационные кнопки увеличили экран; поля нужно показать целиком.
    for _ in range(4):
        scroll()
    for index, value in enumerate((url, key)):
        fields = [
            n
            for n in dump().iter("node")
            if n.get("class") == "android.widget.EditText"
        ]
        assert len(fields) == 2
        tap(fields[index])
        adb("shell", "input", "keyevent", "123")
        adb(
            "shell",
            "input",
            "keyevent",
            *(["67"] * (len(fields[index].get("text", "")) + 2)),
        )
        adb("shell", "input", "text", value)
        ime = adb("shell", "dumpsys", "input_method")
        if "mInputShown=true" in ime or "mIsInputViewShown=true" in ime:
            adb("shell", "input", "keyevent", "4")
    tap(find("Сохранить и проверить"))


def main():
    assert adb("shell", "getprop", "ro.kernel.qemu").strip() == "1"
    assert (
        "read-only"
        in (
            ROOT / "android/.gradle/avd/ShadeTask03API35.avd/emu-launch-params.txt"
        ).read_text()
    )
    assert api("/checks/state")["commands"] == 0
    apk = ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"
    adb("install", "-r", str(apk))
    adb("shell", "pm", "clear", PACKAGE)
    adb("reverse", "tcp:8003", "tcp:8003")
    try:
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        fill_settings(BASE + "/api/v1/", API_KEY)
        find("Ключ принят")
        open_voice()
        find("Разрешить микрофон")
        assert api("/checks/state")["stt_calls"] == 0
        adb("shell", "pm", "grant", PACKAGE, "android.permission.RECORD_AUDIO")
        adb("shell", "am", "force-stop", PACKAGE)
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        open_voice()
        record()
        assert api("/checks/state")["commands"] == 0
        screenshot = ROOT / "android/.gradle/task25-preview.png"
        screenshot.write_bytes(
            subprocess.check_output(
                [
                    str(ROOT / "android/.gradle/sdk/platform-tools/adb"),
                    "-s",
                    "emulator-5554",
                    "exec-out",
                    "screencap",
                    "-p",
                ]
            )
        )
        tap(find("Подтверждаю действие"))
        find("Команда принята Home Assistant")
        assert api("/checks/state")["commands"] == 1
        tap(find("Проверить состояние запроса"))
        find("Команда принята Home Assistant")
        assert api("/checks/state")["commands"] == 1
        print(
            "PASS: AudioRecord/WAV→preview→explicit confirm; repeat status sends no command",
            flush=True,
        )
        api("/checks/mode/unknown", True)
        record()
        tap(find("Подтверждаю действие"))
        find("Результат неизвестен")
        assert api("/checks/state")["commands"] == 2
        tap(find("Проверить состояние запроса"))
        find("Результат неизвестен")
        assert api("/checks/state")["commands"] == 2
        print("PASS: unknown is not replayed", flush=True)
        # Остановка экрана прекращает захват до новой отправки.
        api("/checks/mode/normal", True)
        before = api("/checks/state")["stt_calls"]
        tap(find("Записать команду", True))
        find("Идёт запись")
        adb("shell", "input", "keyevent", "3")
        time.sleep(1)
        assert api("/checks/state")["stt_calls"] == before
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        # После Resume транскрипт исчезает, остаётся только metadata Core-истории.
        assert not nodes("Распознано:")
        api("/checks/mode/denied", True)
        tap(find("Обновить историю"))
        find("Ключ не принят")
        body = " ".join(n.get("text", "") for n in dump().iter("node"))
        assert "private synthetic" not in body and "свет на кухне" not in body
        names = adb("exec-out", "run-as", PACKAGE, "ls", "shared_prefs").splitlines()
        assert len(names) <= 30
        prefs = ""
        for name in names:
            if re.fullmatch(r"[a-zA-Z0-9_.-]+\.xml", name):
                prefs += adb(
                    "exec-out", "run-as", PACKAGE, "cat", "shared_prefs/" + name
                )
        assert TEXT not in prefs and API_KEY not in prefs
        state = api("/checks/state")
        assert state["frames"] and all(4000 <= n <= 160000 for n in state["frames"])
        result = dict(
            result="PASS",
            apk_sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),
            api_level=35,
            read_only_avd=True,
            actual_core=True,
            native_stt=False,
            synthetic_ha=True,
            physical_phone=False,
            stt_calls=state["stt_calls"],
            pcm_frames=state["frames"],
            ha_commands=state["commands"],
            checks=[
                "permission gate",
                "AudioRecord WAV bounds",
                "preview does not execute",
                "explicit confirmed=true",
                "GET does not replay",
                "unknown",
                "Pause stops capture/clears speech",
                "401 clears",
                "prefs no speech/key",
            ],
        )
        (ROOT / "docs/reports/task-25-android-emulator.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )
        print(json.dumps(result))
    finally:
        adb("shell", "am", "force-stop", PACKAGE)
        adb("reverse", "--remove", "tcp:8003")
        adb("shell", "rm", "-f", "/sdcard/task09-ui.xml")


if __name__ == "__main__":
    main()
