"""TASK-19: AOSP35/сохранённый APK -> настоящий Core, синтетический разбор без GGUF."""

import hashlib
import json
import time
import urllib.request
from pathlib import Path

from check_access import fill_settings, scroll, top
from check_emulator import PACKAGE, adb, dump, find, nodes, tap, wait
from results_server import API_KEY, PRIVATE, TEXT

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:8003"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(path, body=None):
    request = urllib.request.Request(
        BASE + path,
        data=b"{}" if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with opener.open(request, timeout=8) as response:
        return json.load(response)


def mode(value):
    print("Проверка Core state:", value, flush=True)
    api("/checks/mode/" + value, {})
    time.sleep(5.5)


def text():
    return " ".join(node.get("text", "") for node in dump().iter("node"))


def page_button(label):
    # 20 высоких карточек не укладываются в шесть свайпов общего helper.
    for _ in range(24):
        found = nodes(label)
        if found:
            return found[0]
        scroll()
    raise AssertionError("Не найдена кнопка страницы: " + label)


def main():
    output = ROOT / "docs/reports/task-19-android-os.json"
    assert not output.exists()
    assert adb("shell", "getprop", "ro.kernel.qemu").strip() == "1"
    assert (
        "read-only"
        in (ROOT / "android/.gradle/avd/ShadeTask03API35.avd/emu-launch-params.txt").read_text()
    )
    assert api("/checks/state")["identity"] == 25
    apk = ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"
    adb("install", "-r", str(apk))
    adb("shell", "pm", "clear", PACKAGE)
    adb("logcat", "-b", "crash", "-c")
    adb("reverse", "tcp:8003", "tcp:8003")
    try:
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        fill_settings(BASE + "/api/v1/", API_KEY)
        find("Ключ принят")
        tap(find("Результаты Core", True))
        find("Всего: 25 · Страница 1")
        tap(find("Стенд Core 25"))
        find("Результат разбора ещё не получен.")
        mode("processing")
        find("Обрабатывается", True)
        mode("processed")
        find("Локальный разбор")
        find("Пункт выдачи")
        find("Часовой пояс разбора")
        find("Asia/Yekaterinburg")
        mode("unsupported")
        find("Формат результата не поддерживается.")
        assert "schema_version" not in text()
        mode("diagnostic")
        find("Проверен конвейер очереди.")
        mode("failed")
        find("Не удалось обработать запись")
        assert PRIVATE not in text()
        mode("deleted")
        find("Запись уже удалена или срок хранения истёк.")
        assert TEXT not in text()
        top()
        tap(find("К списку результатов"))
        find("Всего: 24 · Страница 1")
        print("Проверка страниц20/4", flush=True)
        tap(page_button("Более ранние"))
        find("Всего: 24 · Страница 2", True)
        find("Стенд Core 1")
        top()
        tap(page_button("Более новые"))
        find("Всего: 24 · Страница 1", True)
        adb("shell", "input", "keyevent", "3")
        time.sleep(2)
        before = api("/checks/state")["reads"]
        time.sleep(6)
        assert api("/checks/state")["reads"] == before, "Polling продолжается после STOP"
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        wait("Всего: 24 · Страница 1")
        mode("denied")
        find("Ключ не принят. Проверьте подключение к Core.")
        assert "Стенд Core" not in text() and PRIVATE not in text()
        prefs = adb("exec-out", "run-as", PACKAGE, "cat", "shared_prefs/shade_prefs.xml")
        assert API_KEY not in prefs and TEXT not in prefs and PRIVATE not in prefs
        assert api("/checks/state")["commands"] == 0
        assert "FATAL EXCEPTION" not in adb("logcat", "-b", "crash", "-d")
        result = dict(
            result="PASS",
            apk_sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),
            api_level=35,
            read_only_avd=True,
            actual_core=True,
            synthetic_extraction=True,
            native_llm=False,
            hardware=False,
            ha_commands=0,
            checks=[
                "pending-processing-processed polling",
                "fields/timezone",
                "unknown schema",
                "diagnostic vs LLM",
                "failed safe fallback",
                "404 clears text",
                "pagination20/4",
                "STOP pauses polling",
                "resume",
                "401 clears page",
                "prefs private",
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
