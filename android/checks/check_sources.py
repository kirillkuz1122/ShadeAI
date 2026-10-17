"""TASK-10: синтетический NotificationListener → Room → отдельный Core, только эмулятор."""

import json
import sqlite3
import subprocess
import time
import urllib.request

from check_emulator import (
    ADB,
    API_KEY,
    PACKAGE,
    ROOT,
    URL,
    adb,
    dump,
    fill,
    find,
    save,
    scroll,
    tap,
)

ARTIFACTS = ROOT / "android/.gradle/task10-checks"
ALLOWED = "ru.ozon.app.android"
PRIVATE = "org.telegram.messenger"
COMPONENT = PACKAGE + "/com.shadeai.app.service.ShadeNotificationListener"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def total():
    response = OPENER.open(
        urllib.request.Request(
            URL + "notifications", headers={"Authorization": "Bearer " + API_KEY}
        ),
        timeout=5,
    )
    return json.load(response)["total"]


def room_count():
    # Снимок debug-БД после завершения записи, включая WAL; рабочая БД не используется.
    for name in ("shade.db", "shade.db-wal", "shade.db-shm"):
        path = ARTIFACTS / name
        path.unlink(missing_ok=True)
        result = subprocess.run(
            [
                str(ADB),
                "-s",
                "emulator-5554",
                "exec-out",
                "run-as",
                PACKAGE,
                "cat",
                "databases/" + name,
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            path.write_bytes(result.stdout)
    with sqlite3.connect(ARTIFACTS / "shade.db") as db:
        return db.execute("SELECT count(*) FROM pending_notifications").fetchone()[0]


def sources_screen():
    adb(
        "shell",
        "am",
        "start",
        "-W",
        "-n",
        PACKAGE + "/.MainActivity",
        "-f",
        "0x34000000",
    )
    for _ in range(3):
        scroll(True)
    texts = [node.get("text") for node in dump().iter("node")]
    if "К подключению" not in texts:
        tap(find("Уведомления и источники", top=True))
    find("Доступ Android")


def exact_tap(text):
    # Диалог появляется после анимации переключателя: не читать предыдущий экран как подтверждение.
    for _ in range(6):
        for node in dump().iter("node"):
            if (
                node.get("text", "").casefold() == text.casefold()
                and node.get("enabled") == "true"
            ):
                tap(node)
                return
        time.sleep(0.3)
    raise AssertionError("Не найден системный элемент " + text)


def checked(label):
    find(label)
    for node in dump().iter("node"):
        if node.get("checkable") == "true" and any(
            child.get("text") == label for child in node.iter("node")
        ):
            return node.get("checked") == "true"
    raise AssertionError("Не найден переключатель " + label)


def publish(kind, identifier, package=ALLOWED):
    adb(
        "shell",
        "am",
        "start",
        "-n",
        package + "/com.shadeai.fixture.PublisherActivity",
        "--es",
        "kind",
        kind,
        "--ei",
        "id",
        str(identifier),
    )
    time.sleep(1.5)


def assert_counts(expected_core, expected_room):
    for _ in range(20):
        if total() == expected_core and room_count() == expected_room:
            return
        time.sleep(0.3)
    raise AssertionError(
        f"Ожидались Core={expected_core}, Room={expected_room}; получены {total()}, {room_count()}"
    )


def screenshot(name):
    result = subprocess.check_output(
        [str(ADB), "-s", "emulator-5554", "exec-out", "screencap", "-p"]
    )
    (ARTIFACTS / name).write_bytes(result)


def setup():
    assert adb("shell", "getprop", "ro.kernel.qemu").strip() == "1", "Нужен эмулятор"
    assert total() == 0, "Нужен свежий checks/core_server.py"
    for package in (ALLOWED, PRIVATE):
        assert not adb("shell", "pm", "list", "packages", package).strip(), (
            "Пакет уже установлен; не заменяем его"
        )
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    for flavor, package in (("allowed", ALLOWED), ("privateSource", PRIVATE)):
        apk = next(
            (
                ROOT / "android/checks/publisher/build/outputs/apk" / flavor / "debug"
            ).glob("*.apk")
        )
        adb("install", str(apk))
        adb("shell", "pm", "grant", package, "android.permission.POST_NOTIFICATIONS")
    adb(
        "install", "-r", str(ROOT / "android/app/build/outputs/apk/debug/app-debug.apk")
    )
    adb("shell", "cmd", "notification", "disallow_listener", COMPONENT)
    adb("shell", "pm", "clear", PACKAGE)
    adb("reverse", "tcp:8000", "tcp:8000")
    adb("logcat", "-c")
    adb(
        "shell",
        "am",
        "start",
        "-W",
        "-n",
        PACKAGE + "/.MainActivity",
        "-f",
        "0x34000000",
    )
    fill(0, URL)
    fill(1, API_KEY)
    save()
    find("Ключ принят")
    sources_screen()
    find("Доступ Android не выдан")
    for label in ("Ozon", "Wildberries", "Яндекс Go"):
        assert not checked(label)
    print("PASS: чистая установка, ключ и три выключенных источника", flush=True)


def grant_in_settings():
    tap(find("Настроить доступ Android", top=True))
    tap(find("Shade AI"))
    exact_tap("Allow notification access")
    exact_tap("Allow")
    adb("shell", "input", "keyevent", "4")
    adb("shell", "input", "keyevent", "4")
    sources_screen()
    find("Доступ Android выдан")
    print("PASS: доступ выдан через системный экран, состояние обновлено", flush=True)


def scenarios():
    publish("disabled", 1)
    assert_counts(0, 0)
    sources_screen()
    tap(find("Ozon"))
    publish("order", 2)
    assert_counts(1, 1)
    response = OPENER.open(
        urllib.request.Request(
            URL + "notifications", headers={"Authorization": "Bearer " + API_KEY}
        ),
        timeout=5,
    )
    item = json.load(response)["items"][0]
    assert item["title"] == "Синтетическая доставка order"
    assert item["text"] == "Заказ подготовлен — синтетическая проверка"
    for identifier, kind in enumerate(("sensitive", "ongoing", "summary", "local"), 3):
        publish(kind, identifier)
        assert_counts(1, 1)
    publish("private", 7, PRIVATE)
    assert_counts(1, 1)
    print(
        "PASS: выбранное проходит, чувствительное/служебное/мессенджер не попадают в Room/Core",
        flush=True,
    )
    sources_screen()
    screenshot("task-10-emulator.png")
    tap(find("Ozon"))
    assert_counts(1, 0)
    publish("disabled-again", 8)
    assert_counts(1, 0)
    adb("shell", "am", "force-stop", PACKAGE)
    sources_screen()
    assert not checked("Ozon")
    tap(find("Ozon"))
    adb("shell", "am", "force-stop", PACKAGE)
    sources_screen()
    assert checked("Ozon")
    print(
        "PASS: отключение удаляет буфер и блокирует приём; выбор переживает force-stop",
        flush=True,
    )
    # Отдельно проверяем накопление без сети и удаление при отключении источника.
    adb("reverse", "--remove", "tcp:8000")
    adb("shell", "cmd", "notification", "disallow_listener", COMPONENT)
    adb("shell", "cmd", "notification", "allow_listener", COMPONENT)
    time.sleep(1)
    publish("offline", 9)
    for _ in range(20):
        if room_count() == 1:
            break
        time.sleep(0.3)
    assert room_count() == 1
    sources_screen()
    tap(find("Ozon"))
    assert room_count() == 0
    adb("reverse", "tcp:8000", "tcp:8000")
    adb("shell", "cmd", "notification", "disallow_listener", COMPONENT)
    adb("shell", "cmd", "notification", "allow_listener", COMPONENT)
    time.sleep(1.5)
    assert_counts(1, 0)
    print(
        "PASS: выключенный офлайн-источник не отправляется при переподключении",
        flush=True,
    )
    sources_screen()
    tap(find("Ozon"))
    publish("before-revoke", 10)
    assert_counts(2, 1)
    sources_screen()
    tap(find("Настроить доступ Android", top=True))
    tap(find("Shade AI"))
    exact_tap("Allow notification access")
    exact_tap("Turn off")
    adb("shell", "input", "keyevent", "4")
    adb("shell", "input", "keyevent", "4")
    sources_screen()
    find("Доступ Android не выдан")
    assert_counts(2, 0)
    publish("revoked", 11)
    assert_counts(2, 0)
    sources_screen()
    screenshot("task-10-revoked.png")
    crashes = adb("logcat", "-b", "crash", "-d")
    assert "FATAL EXCEPTION" not in crashes
    logs = adb("logcat", "-d")
    assert API_KEY not in logs and "Код 1234" not in logs
    print(
        "PASS: отзыв через Android очищает буфер и останавливает приём; crash log пуст",
        flush=True,
    )


def main():
    setup()
    grant_in_settings()
    scenarios()
    for package in (ALLOWED, PRIVATE):
        adb("uninstall", package)
    adb("shell", "rm", "-f", "/sdcard/task09-ui.xml")
    print("TASK-10: все сценарии пройдены, тестовые издатели удалены", flush=True)


if __name__ == "__main__":
    main()
