"""AOSP35 owner UI→настоящий Core26/fakeHA, одноразовый PIN и FLAG_SECURE."""

import hashlib
import json
import re
import struct
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import check_emulator
from access_server import API_KEY, ENTITY, KEYPAD_KEY, TEXT
from check_emulator import PACKAGE, adb, dump, find, tap

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:8003"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(path, body=None, keypad=False):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": "Bearer " + (KEYPAD_KEY if keypad else API_KEY),
            "Content-Type": "application/json",
        },
    )
    try:
        with opener.open(request, timeout=8) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def slow_scroll(top=False):
    sizes = re.findall(r"(\d+)x(\d+)", adb("shell", "wm", "size"))
    width, height = map(int, sizes[-1])
    upper, lower = str(int(height * 0.25)), str(int(height * 0.82))
    adb(
        "shell",
        "input",
        "swipe",
        str(int(width * 0.85)),
        upper if top else lower,
        str(int(width * 0.85)),
        lower if top else upper,
        "800",
    )


# На загруженном хосте короткий 200мс swipe иногда не сдвигает Compose ScrollView.
check_emulator.scroll = slow_scroll
scroll = slow_scroll


def fill_settings(url, key):
    for index, value in enumerate((url, key)):
        for attempt in range(10):
            fields = [
                node
                for node in dump().iter("node")
                if node.get("class") == "android.widget.EditText"
            ]
            if len(fields) == 2:
                break
            scroll(attempt >= 5)
        assert len(fields) == 2
        tap(fields[index])
        adb("shell", "input", "keyevent", "123")
        adb("shell", "input", "keyevent", *(["67"] * (len(fields[index].get("text", "")) + 2)))
        adb("shell", "input", "text", value)
        ime = adb("shell", "dumpsys", "input_method")
        if "mInputShown=true" in ime or "mIsInputViewShown=true" in ime:
            adb("shell", "input", "keyevent", "4")
    tap(find("Сохранить и проверить"))


def top():
    for _ in range(7):
        scroll(True)


def open_access():
    tap(find("Доступ для доставки", True))
    find("Результаты обработки доставки")


def select_source(identity):
    top()
    tap(find(f"Доставка №{identity} ·"))
    find(f"Проверка доставки №{identity}")
    tap(find("Выбрать: " + ENTITY))


def check_label(text):
    label = find(text)
    label_bounds = list(map(int, re.findall(r"\d+", label.get("bounds", ""))))
    boxes = [node for node in dump().iter("node") if node.get("checkable") == "true"]
    candidates = []
    for box in boxes:
        bounds = list(map(int, re.findall(r"\d+", box.get("bounds", ""))))
        if bounds[0] < label_bounds[0]:
            candidates.append((abs(bounds[1] - label_bounds[1]), box))
    assert candidates and min(distance for distance, _ in candidates) < 40, "Checkbox не найден"
    tap(min(candidates, key=lambda item: item[0])[1])


def create(identity):
    select_source(identity)
    check_label("Доставку и её контекст проверил")
    check_label("Разрешаю одно открытие выбранного замка по PIN")
    tap(find("Создать одноразовый PIN"))
    find("PIN показывается один раз", True)
    pin_nodes = [
        node.get("text", "")
        for node in dump().iter("node")
        if re.fullmatch(r"[0-9]{6}", node.get("text", ""))
    ]
    assert len(pin_nodes) == 1
    return pin_nodes[0]


def screenshot():
    data = subprocess.check_output(
        [
            str(ROOT / "android/.gradle/sdk/platform-tools/adb"),
            "-s",
            "emulator-5554",
            "exec-out",
            "screencap",
            "-p",
        ]
    )
    return data


def black_ratio(image, bounds):
    # Pillow уже есть у системного Python, приложения/Core этой зависимости нет.
    script = """import io,sys
from PIL import Image
image=Image.open(io.BytesIO(sys.stdin.buffer.read())).convert('RGB')
pixels=list(image.crop(tuple(map(int,sys.argv[1:]))).getdata())
print(sum(max(pixel)<8 for pixel in pixels)/len(pixels))
"""
    return float(
        subprocess.check_output(["/usr/bin/python", "-c", script, *map(str, bounds)], input=image)
    )


def same_ratio(first, second, bounds):
    script = """import io,sys,struct
from PIL import Image
data=sys.stdin.buffer.read();length=struct.unpack('>I',data[:4])[0]
a=Image.open(io.BytesIO(data[4:4+length])).convert('RGB')
b=Image.open(io.BytesIO(data[4+length:])).convert('RGB')
bounds=tuple(map(int,sys.argv[1:]));a=list(a.crop(bounds).getdata());b=list(b.crop(bounds).getdata())
print(sum(max(abs(x-y) for x,y in zip(p,q))<=2 for p,q in zip(a,b))/len(a))
"""
    return float(
        subprocess.check_output(
            ["/usr/bin/python", "-c", script, *map(str, bounds)],
            input=struct.pack(">I", len(first)) + first + second,
        )
    )


def main():
    output = ROOT / "docs/reports/task-26-android-emulator.json"
    assert not output.exists(), "Существующий отчёт не перезаписывается"
    assert adb("shell", "getprop", "ro.kernel.qemu").strip() == "1"
    assert (
        "read-only"
        in (ROOT / "android/.gradle/avd/ShadeTask03API35.avd/emu-launch-params.txt").read_text()
    )
    control = api("/checks/state")[1]
    assert control["commands"] == 0 and len(control["sources"]) == 3
    apk = ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"
    adb("install", "-r", str(apk))
    adb("shell", "pm", "clear", PACKAGE)
    adb("reverse", "tcp:8003", "tcp:8003")
    pins = []
    try:
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        fill_settings(BASE + "/api/v1/", API_KEY)
        find("Ключ принят")
        open_access()
        # Сравнить защищённый recents-placeholder без PIN и после показа PIN.
        adb("shell", "input", "keyevent", "187")
        time.sleep(1.5)
        baseline = screenshot()
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        time.sleep(1)
        first = create(control["sources"][0])
        pins.append(first)
        print("PASS: owner consent/create did not unlock", flush=True)
        assert api("/checks/state")[1]["commands"] == 0
        window = adb("shell", "dumpsys", "window", "windows")
        assert "SECURE" in window
        image = screenshot()
        width, height = struct.unpack(">II", image[16:24])
        body_black = black_ratio(
            image, (width // 10, height // 5, width * 9 // 10, height * 4 // 5)
        )
        assert body_black > 0.99, "FLAG_SECURE не скрыл содержимое screenshot"
        print("PASS: FLAG_SECURE screen capture", flush=True)
        # OS-обзор сравнивается с placeholder до PIN; он может быть цветным.
        adb("shell", "input", "keyevent", "187")
        time.sleep(1)
        overview = screenshot()
        recents_black = black_ratio(
            overview,
            (width * 3 // 10, height * 3 // 10, width * 7 // 10, height * 6 // 10),
        )
        recents_same = same_ratio(
            baseline, overview, (width // 4, height // 4, width * 3 // 4, height * 3 // 4)
        )
        assert recents_same > 0.995, "Recents изменился при показе PIN: нужна проверка placeholder"
        print("PASS: recents protected placeholder", flush=True)
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        time.sleep(1)
        body = " ".join(node.get("text", "") for node in dump().iter("node"))
        assert first not in body and TEXT not in body
        code, result = api("/api/v1/access/keypad/verify", dict(entity_id=ENTITY, pin=first), True)
        assert code == 200 and result["state"] == "used"
        assert (
            api("/api/v1/access/keypad/verify", dict(entity_id=ENTITY, pin=first), True)[0] == 403
        )
        assert api("/checks/state")[1]["commands"] == 1
        print("PASS: limited keypad one use", flush=True)
        second = create(control["sources"][1])
        pins.append(second)
        tap(find("Отозвать доступ"))
        find("Код отозван")
        assert (
            api("/api/v1/access/keypad/verify", dict(entity_id=ENTITY, pin=second), True)[0] == 403
        )
        print("PASS: owner revoke", flush=True)
        api("/checks/mode/unknown", {})
        third = create(control["sources"][2])
        pins.append(third)
        code, result = api("/api/v1/access/keypad/verify", dict(entity_id=ENTITY, pin=third), True)
        assert code == 200 and result["state"] == "unknown"
        tap(find("Проверить состояние доступа"))
        find("Результат неизвестен")
        check_label("Дверь проверил вручную; понимаю, что отзыв не запирает её")
        tap(find("Отозвать доступ"))
        find("Код отозван")
        assert api("/checks/state")[1]["commands"] == 2
        api("/checks/mode/denied", {})
        tap(find("Обновить список доступов"))
        find("Ключ не принят")
        body = " ".join(node.get("text", "") for node in dump().iter("node"))
        assert TEXT not in body and not any(pin in body for pin in pins)
        prefs = ""
        for name in adb("exec-out", "run-as", PACKAGE, "ls", "shared_prefs").splitlines():
            assert re.fullmatch(r"[a-zA-Z0-9_.-]+\.xml", name)
            prefs += adb("exec-out", "run-as", PACKAGE, "cat", "shared_prefs/" + name)
        assert TEXT not in prefs and API_KEY not in prefs and KEYPAD_KEY not in prefs
        assert not any(pin in prefs for pin in pins)
        # Нельзя выводить или сохранять сами PIN/контекст в отчёте.
        result = dict(
            result="PASS",
            apk_sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),
            api_level=35,
            read_only_avd=True,
            actual_core=True,
            synthetic_llm_result=True,
            synthetic_ha=True,
            hardware=False,
            ha_unlocks=2,
            screen_body_black_ratio=body_black,
            recents_center_black_ratio=recents_black,
            recents_placeholder_similarity=recents_same,
            checks=[
                "explicit owner source/target/two consents",
                "create does not unlock",
                "PIN once",
                "focus/recents clears PIN/source",
                "FLAG_SECURE screenshot",
                "recents placeholder unchanged with PIN",
                "limited keypad one use",
                "revoke",
                "unknown manual checked=true",
                "401 clears",
                "prefs no PIN/source/plain keys",
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
