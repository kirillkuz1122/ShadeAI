"""TASK-15: настоящий HTTP, SIGKILL/рестарт и SQLite; только синтетический стенд."""

import asyncio
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import closing
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from uuid import uuid4

import httpx

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))
PRIVATE = "synthetic-untrusted-processor-error-839174"


def serve_core():
    import uvicorn

    from app import main
    from app.services.notification.processor import ProcessingResult
    from app.services.notification.worker import NotificationWorker

    async def processor(notification):
        if notification.text == "Синтетика ожидание" and os.environ.get("STAND_RELEASE") != "yes":
            await asyncio.sleep(3600)
        if notification.text == "Синтетика ошибка":
            raise RuntimeError(PRIVATE)
        if notification.text == "Синтетика неверный результат":
            return {"processor": "diagnostic", "raw": PRIVATE}
        if notification.text == "Синтетика таймаут":
            await asyncio.sleep(1)
        return ProcessingResult(processor="diagnostic")

    main.NotificationWorker = lambda **_: NotificationWorker(processor)
    uvicorn.run(
        main.create_app(), fd=int(os.environ["STAND_FD"]), log_level="critical", access_log=False
    )


def scenario(workspace):
    key, ha_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    commands = []
    state = {
        "entity_id": "light.test",
        "state": "on",
        "attributes": {},
        "last_changed": "2026-10-18T01:00:00Z",
        "last_updated": "2026-10-18T01:00:00Z",
    }

    class HA(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_request(self):
            assert self.headers.get("Authorization") == f"Bearer {ha_token}"
            if self.command == "POST":
                assert self.path == "/api/services/light/turn_on"
                commands.append(self.rfile.read(int(self.headers["Content-Length"])))
                payload = []
            elif self.path == "/api/":
                payload = {"message": "API running."}
            else:
                assert self.path == "/api/states/light.test"
                payload = state
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        do_GET = handle_request
        do_POST = handle_request

    ha = HTTPServer(("127.0.0.1", 0), HA)
    thread = threading.Thread(target=ha.serve_forever, daemon=True)
    thread.start()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    values = {
        "SHADE_API_KEY": key,
        "DB_URL": "sqlite+aiosqlite:///./worker.db",
        "HA_BASE_URL": f"http://127.0.0.1:{ha.server_port}",
        "HA_TOKEN": ha_token,
        "HA_TIMEOUT_SECONDS": "1",
        "HA_TELEMETRY_ENTITIES": "[]",
        "SENSOR_RETENTION_DAYS": "90",
        "SENSOR_HISTORY_MAX_ROWS": "1000",
        "NOTIFICATION_PROCESSOR": "diagnostic",
        "NOTIFICATION_QUEUE_SIZE": "3",
        "NOTIFICATION_PROCESSING_TIMEOUT_SECONDS": "0.4",
        "NOTIFICATION_SHUTDOWN_SECONDS": "0.1",
        "NOTIFICATION_ALLOWED_APPS": '["ru.ozon.app.android"]',
        "NOTIFICATION_RETENTION_DAYS": "30",
        "CORS_ORIGINS": "[]",
        "LOG_DIR": "./logs",
        "EVENT_RETENTION_DAYS": "90",
        "LOG_MAX_BYTES": "1048576",
        "LOG_BACKUP_COUNT": "3",
        "STAND_FD": str(listener.fileno()),
    }
    env = {
        name: value
        for name, value in os.environ.items()
        if name.lower() not in {field.lower() for field in values}
    }
    env.update(values)
    child = None

    def start(released=False):
        return subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--serve"],
            cwd=workspace,
            env=env
            | {
                "STAND_RELEASE": "yes" if released else "no",
                "NOTIFICATION_PROCESSING_TIMEOUT_SECONDS": "0.4" if released else "30",
            },
            pass_fds=(listener.fileno(),),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def stop(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        output = process.communicate()[0]
        assert (
            PRIVATE.encode() not in output
            and key.encode() not in output
            and ha_token.encode() not in output
        )

    try:
        child = start()
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}/api/v1",
            trust_env=False,
            headers={"Authorization": f"Bearer {key}"},
            timeout=1,
        ) as http:

            def ready():
                try:
                    return http.get("/health").status_code == 200
                except httpx.HTTPError:
                    return False

            def wait(condition):
                deadline = time.monotonic() + 8
                while not condition():
                    assert child.poll() is None, "Core неожиданно остановился"
                    assert time.monotonic() < deadline, "Превышено ожидание стенда"
                    time.sleep(0.02)

            def send(text, event_id=None):
                body = {
                    "app_name": "ru.ozon.app.android",
                    "title": "Проверка очереди",
                    "text": text,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "event_id": event_id or str(uuid4()),
                }
                response = http.post("/notifications", json=body)
                assert response.status_code == 201 and response.json()["status"] == "stored"
                return response.json()["id"], body

            def detail(row_id):
                response = http.get(f"/notifications/{row_id}")
                response.raise_for_status()
                return response.json()

            wait(ready)
            done, _ = send("Синтетика готовая")
            wait(lambda: detail(done)["processing_status"] == "processed")
            held, body = send("Синтетика ожидание")
            wait(lambda: detail(held)["processing_status"] == "processing")
            started = time.monotonic()
            assert http.get("/health").json()["services"]["notification_worker"] == "processing"
            assert (
                http.post("/devices/light.test/command", json={"action": "turn_on"}).status_code
                == 200
            )
            pending = [send(f"Синтетика пачка {i}")[0] for i in range(12)]
            assert time.monotonic() - started < 2
            assert http.post("/notifications", json=body).json()["status"] == "duplicate"
            child.kill()
            child.wait(timeout=3)
            stop(child)
            with closing(sqlite3.connect(workspace / "worker.db")) as db:
                assert db.execute(
                    "SELECT processing_status FROM notifications_raw WHERE id=?", (held,)
                ).fetchone() == ("processing",)
            child = start(released=True)
            wait(ready)
            wait(lambda: detail(pending[-1])["processing_status"] == "processed")
            assert detail(held)["processing_attempts"] == 2
            assert detail(done)["processing_attempts"] == 1
            assert detail(held)["processed_data"] == {"processor": "diagnostic", "llm": False}
            for text, expected in [
                ("Синтетика ошибка", "PROCESSOR_ERROR"),
                ("Синтетика неверный результат", "INVALID_RESULT"),
                ("Синтетика таймаут", "PROCESSOR_TIMEOUT"),
            ]:
                row_id, _ = send(text)
                wait(lambda row_id=row_id: detail(row_id)["processing_status"] == "failed")
                assert detail(row_id)["processing_error_code"] == expected
            fresh, _ = send("Синтетика после отказов")
            wait(lambda: detail(fresh)["processing_status"] == "processed")
            assert len(commands) == 1
        stop(child)
        child = None
        with closing(sqlite3.connect(workspace / "worker.db")) as db:
            assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            before = db.execute(
                "SELECT id,app_name,title,text,timestamp,dedupe_key,payload_hash "
                "FROM notifications_raw ORDER BY id"
            ).fetchall()
            sequence = db.execute(
                "SELECT seq FROM sqlite_sequence WHERE name='notifications_raw'"
            ).fetchone()[0]
        for direction, revision in (("downgrade", "0005_sensor_history"), ("upgrade", "head")):
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "alembic",
                    "-c",
                    str(CORE / "alembic.ini"),
                    direction,
                    revision,
                ],
                cwd=workspace,
                env=env,
                check=True,
                capture_output=True,
            )
        with closing(sqlite3.connect(workspace / "worker.db")) as db:
            assert (
                db.execute(
                    "SELECT id,app_name,title,text,timestamp,dedupe_key,payload_hash "
                    "FROM notifications_raw ORDER BY id"
                ).fetchall()
                == before
            )
            assert (
                db.execute(
                    "SELECT seq FROM sqlite_sequence WHERE name='notifications_raw'"
                ).fetchone()[0]
                >= sequence
            )
        for path in workspace.rglob("*"):
            if path.is_file():
                data = path.read_bytes()
                assert (
                    PRIVATE.encode() not in data
                    and key.encode() not in data
                    and ha_token.encode() not in data
                )
        print(
            "TASK-15 loopback: HTTP/HA/batch/duplicate/SIGKILL/restart/errors/privacy/migrations OK"
        )
    finally:
        if child:
            stop(child)
        listener.close()
        ha.shutdown()
        ha.server_close()
        thread.join(timeout=2)


def main():
    if "--serve" in sys.argv:
        serve_core()
        return
    cache = CORE / ".pytest_cache"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="task15-loopback-", dir=cache) as workspace:
        scenario(Path(workspace))


if __name__ == "__main__":
    main()
