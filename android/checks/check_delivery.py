"""TASK-12: WorkManager → изолированный Core с потерей ответа/401; только emulator-5554."""

import json
import socket
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar
from uuid import uuid4

import check_buffer
from check_buffer import core_items, publish, snapshot
from check_emulator import API_KEY, PACKAGE, ROOT, adb, fill, find, save, tap
from check_sources import ALLOWED, COMPONENT, OPENER, checked, sources_screen

check_buffer.ARTIFACTS = ROOT / "android/.gradle/task12-checks/snapshot"
URL = "http://10.0.2.2:8001/api/v1/"


class FaultProxy(BaseHTTPRequestHandler):
    mode = "ok"
    calls: ClassVar[list[str]] = []
    lock = threading.Lock()

    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.forward()

    def do_POST(self):
        self.forward()

    def forward(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        post = self.command == "POST"
        with self.lock:
            mode = type(self).mode
            if post:
                self.calls.append(json.loads(body)["event_id"])
                if mode == "drop-once":
                    type(self).mode = "ok"
        if post and mode in {"unauthorized", "invalid"}:
            self.send_response(401 if mode == "unauthorized" else 422)
            self.end_headers()
            self.wfile.write(b'{"detail":"synthetic fault"}')
            return
        request = urllib.request.Request(
            "http://127.0.0.1:8000" + self.path,
            data=body if post else None,
            headers={
                "Authorization": self.headers.get("Authorization", ""),
                "Content-Type": "application/json",
            },
            method=self.command,
        )
        try:
            response = OPENER.open(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            data = response.read()
            if post and mode == "drop-once":
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            self.send_response(response.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)


def wait_for(predicate, description, timeout=100):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        rows = snapshot()
        if predicate(rows):
            return rows
        time.sleep(0.5)
    raise AssertionError(
        description + ": " + str([(r["id"], r["status"], r["lastError"]) for r in rows])
    )


def check_batch():
    # Только синтетический debug-стенд: SQL-подготовка проверяет WorkManager, а не перехват 105 callbacks.
    assert adb("shell", "getprop", "ro.kernel.qemu").strip() == "1"
    with OPENER.open(
        urllib.request.Request(
            "http://127.0.0.1:8000/api/v1/notifications?limit=1",
            headers={"Authorization": "Bearer " + API_KEY},
        ),
        timeout=5,
    ) as response:
        before = json.load(response)["total"]
    assert before == 5, "Сначала нужен полный синтетический сценарий TASK-12"
    adb("shell", "am", "force-stop", PACKAGE)
    existing = snapshot()
    assert len(existing) in {0, 6}, "Нужен буфер синтетического стенда"
    initial_count = len(existing)
    database = check_buffer.ARTIFACTS / "shade.db"
    now = int(time.time() * 1000)
    with sqlite3.connect(database) as db:
        db.executemany(
            """INSERT INTO pending_notifications
            (packageName, title, text, postTime, eventId, sourceKey, contentHash, status, createdAt, completedAt, attempts, lastError)
            VALUES (?, ?, ?, ?, ?, NULL, '', 'PENDING', ?, NULL, 0, NULL)""",
            [
                (
                    ALLOWED,
                    "Синтетическая доставка",
                    "Проверка фоновой очереди",
                    now,
                    str(uuid4()),
                    now,
                )
                for _ in range(105)
            ],
        )
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    remote = "/data/local/tmp/shade-task12-buffer.db"
    try:
        adb("push", str(database), remote)
        adb(
            "shell",
            "run-as",
            PACKAGE,
            "rm",
            "-f",
            "databases/shade.db-wal",
            "databases/shade.db-shm",
        )
        adb("shell", "run-as", PACKAGE, "cp", remote, "databases/shade.db")
        adb("shell", "cmd", "notification", "allow_listener", COMPONENT)
        adb("shell", "am", "start", "-W", "-n", PACKAGE + "/.MainActivity")
        rows = wait_for(
            lambda r: (
                len(r) == initial_count + 105
                and all(x["status"] == "SENT" for x in r[initial_count:])
            ),
            "WorkManager не продолжил вторую порцию",
            timeout=120,
        )
        assert all(x["attempts"] == 1 for x in rows[initial_count:])
        with OPENER.open(
            urllib.request.Request(
                "http://127.0.0.1:8000/api/v1/notifications?limit=1",
                headers={"Authorization": "Bearer " + API_KEY},
            ),
            timeout=5,
        ) as response:
            assert json.load(response)["total"] == before + 105
        print(
            "PASS: 105 синтетических строк в debug Room → WorkManager несколькими порциями → Core, без повторной отправки подтверждённых",
            flush=True,
        )
    finally:
        adb("shell", "rm", "-f", remote)


def main():
    assert adb("shell", "getprop", "ro.kernel.qemu").strip() == "1"
    assert not core_items(), "Нужен свежий checks/core_server.py"
    assert not adb("shell", "pm", "list", "packages", ALLOWED).strip(), (
        "Не заменяем установленное приложение"
    )
    proxy = ThreadingHTTPServer(("127.0.0.1", 8001), FaultProxy)
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    installed = False
    try:
        apk = next(
            (ROOT / "android/checks/publisher/build/outputs/apk/allowed/debug").glob(
                "*.apk"
            )
        )
        adb("install", str(apk))
        installed = True
        adb("shell", "pm", "grant", ALLOWED, "android.permission.POST_NOTIFICATIONS")
        adb(
            "install",
            "-r",
            str(ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"),
        )
        adb("shell", "cmd", "notification", "disallow_listener", COMPONENT)
        adb("shell", "pm", "clear", PACKAGE)
        adb("shell", "svc", "wifi", "enable")
        adb("shell", "svc", "data", "enable")
        adb("logcat", "-c")
        adb("shell", "am", "start", "-W", "-n", PACKAGE + "/.MainActivity")
        fill(0, URL)
        fill(1, API_KEY)
        save()
        find("Ключ принят")
        sources_screen()
        assert not checked("Ozon")
        tap(find("Ozon"))
        assert checked("Ozon")
        adb("shell", "cmd", "notification", "allow_listener", COMPONENT)
        time.sleep(1)
        adb("shell", "svc", "wifi", "disable")
        adb("shell", "svc", "data", "disable")
        time.sleep(2)
        publish("big", 61)
        failed = wait_for(
            lambda r: len(r) == 1 and r[0]["status"] == "PENDING", "Нет офлайн-записи"
        )
        original = failed[0]
        assert original["attempts"] == 0
        assert not core_items()
        adb("shell", "svc", "wifi", "enable")
        rows = wait_for(
            lambda r: len(r) == 1 and r[0]["status"] == "SENT",
            "Нет автоматического восстановления",
        )
        assert rows[0]["eventId"] == original["eventId"]
        assert len(core_items()) == 1
        print(
            "PASS: Wi-Fi/data отключены → Room PENDING → Wi-Fi восстановлен → WorkManager SENT без rebind",
            flush=True,
        )

        FaultProxy.mode = "drop-once"
        publish("inbox", 62)
        failed = wait_for(
            lambda r: len(r) == 2 and r[-1]["status"] == "FAILED",
            "Нет потерянного ответа",
        )
        uuid = failed[-1]["eventId"]
        assert len(core_items()) == 2
        assert failed[-1]["completedAt"] is None
        adb("shell", "am", "force-stop", PACKAGE)
        adb("shell", "am", "start", "-W", "-n", PACKAGE + "/.MainActivity")
        rows = wait_for(
            lambda r: len(r) == 2 and r[-1]["status"] == "SENT",
            "Нет повтора после restart",
        )
        assert rows[-1]["eventId"] == uuid
        assert FaultProxy.calls.count(uuid) == 2
        assert len(core_items()) == 2
        print(
            "PASS: Core сохранил → ответ потерян → restart → тот же UUID → duplicate, две записи Core",
            flush=True,
        )

        FaultProxy.mode = "unauthorized"
        publish("title-only", 63)
        rows = wait_for(
            lambda r: len(r) == 3 and r[-1]["lastError"] == "http_401",
            "Нет классификации 401",
        )
        uuid = rows[-1]["eventId"]
        publish("ticker", 64)
        wait_for(lambda r: len(r) == 4, "Нет следующего события")
        time.sleep(32)
        assert FaultProxy.calls.count(uuid) == 1
        assert len(core_items()) == 2
        print(
            "PASS: 401 останавливает очередь, новое событие и истечение 30 секунд не вызывают HTTP",
            flush=True,
        )
        FaultProxy.mode = "ok"
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
        # Главный экран открывается после перезапуска, ключ уже сохранён.
        save()
        find("Ключ принят")
        rows = wait_for(
            lambda r: len(r) == 4 and all(x["status"] == "SENT" for x in r),
            "Нет продолжения после настроек",
        )
        assert len(core_items()) == 4
        print(
            "PASS: сохранение настроек снимает паузу, вся очередь подтверждена Core",
            flush=True,
        )

        FaultProxy.mode = "invalid"
        publish("big", 65)
        rows = wait_for(
            lambda r: len(r) == 5 and r[-1]["status"] == "REJECTED",
            "Нет терминального 422",
        )
        rejected_uuid = rows[-1]["eventId"]
        assert rows[-1]["lastError"] == "http_422"
        FaultProxy.mode = "ok"
        publish("inbox", 66)
        rows = wait_for(
            lambda r: len(r) == 6 and r[-1]["status"] == "SENT",
            "422 блокирует следующую запись",
        )
        assert FaultProxy.calls.count(rejected_uuid) == 1
        assert len(core_items()) == 5
        log = adb("logcat", "-d")
        assert "FATAL EXCEPTION" not in log and API_KEY not in log
        print(
            "PASS: 422 не повторяется, следующая запись отправляется; нет аварий/ключа в logcat",
            flush=True,
        )
        check_batch()
    finally:
        adb("shell", "svc", "wifi", "enable")
        adb("shell", "svc", "data", "enable")
        adb("shell", "cmd", "notification", "disallow_listener", COMPONENT)
        if installed:
            adb("uninstall", ALLOWED)
        adb("shell", "rm", "-f", "/sdcard/task09-ui.xml")
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    if sys.argv[1:] == ["--batch-only"]:
        proxy = ThreadingHTTPServer(("127.0.0.1", 8001), FaultProxy)
        thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        thread.start()
        try:
            check_batch()
        finally:
            adb("shell", "cmd", "notification", "disallow_listener", COMPONENT)
            proxy.shutdown()
            proxy.server_close()
            thread.join(timeout=5)
    else:
        main()
