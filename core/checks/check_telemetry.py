"""Изолированный loopback-стенд TASK-14; запускать из core/, вне pytest."""

import asyncio
import json
import os
import secrets
import socket
import sys
import tempfile
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, WebSocket
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.server import serve
from websockets.exceptions import InvalidStatus

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))
ENTITY = "sensor.synthetic_temperature"
MOTION = "binary_sensor.synthetic_motion"
PRIVATE = "synthetic-private-attribute-never-store"


def state(value="21", entity=ENTITY, second=0):
    return {
        "entity_id": entity,
        "state": value,
        "attributes": {"unit_of_measurement": "°C", "private": PRIVATE},
        "last_changed": f"2026-10-18T01:00:{second:02d}Z",
        "last_updated": f"2026-10-18T01:00:{second:02d}Z",
    }


async def until(condition, timeout=8):
    async with asyncio.timeout(timeout):
        while not await condition():
            await asyncio.sleep(0.02)


async def start_server(app):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    task = asyncio.create_task(server.serve(sockets=[listener]))

    async def ready():
        if task.done():
            await task
        return server.started

    await until(ready)
    return server, task, port


async def stop_server(server, task):
    server.should_exit = True
    await asyncio.wait_for(task, 8)


async def scenario():
    ha = FastAPI()
    sockets, commands = [], []
    control = {"states": [state(), state("off", MOTION)], "offline": False, "invalid": False}
    token, key = secrets.token_urlsafe(32), secrets.token_urlsafe(32)

    @ha.websocket("/api/websocket")
    async def stream(ws: WebSocket):
        await ws.accept()
        sockets.append(ws)
        if control["offline"]:
            await ws.close(code=1012)
            return
        try:
            await ws.send_json({"type": "auth_required"})
            auth = await ws.receive_json()
            assert auth == {"type": "auth", "access_token": token}
            if control["invalid"]:
                await ws.send_json({"type": "auth_invalid", "message": PRIVATE})
                await ws.close()
                return
            await ws.send_json({"type": "auth_ok"})
            while True:
                message = await ws.receive_json()
                commands.append(message["type"])
                if message["type"] == "subscribe_events":
                    assert message["event_type"] == "state_changed"
                    await ws.send_json({"type": "result", "id": message["id"], "success": True})
                elif message["type"] == "get_states":
                    await ws.send_json(
                        {
                            "type": "result",
                            "id": message["id"],
                            "success": True,
                            "result": control["states"],
                        }
                    )
                elif message["type"] == "ping":
                    await ws.send_json({"type": "pong", "id": message["id"]})
                else:
                    raise AssertionError("Неожиданная команда HA")
        except WebSocketDisconnect:
            pass

    ha_server, ha_task, ha_port = await start_server(ha)
    os.environ.update(
        {
            "SHADE_API_KEY": key,
            "DB_URL": "sqlite+aiosqlite:///./telemetry.db",
            "HA_TOKEN": token,
            "HA_BASE_URL": f"http://127.0.0.1:{ha_port}",
            "HA_TIMEOUT_SECONDS": "1",
            "HA_TELEMETRY_ENTITIES": json.dumps([ENTITY, MOTION]),
            "SENSOR_RETENTION_DAYS": "90",
            "SENSOR_HISTORY_MAX_ROWS": "1000",
            "LOG_DIR": "./logs",
            "CORS_ORIGINS": "[]",
            "NOTIFICATION_ALLOWED_APPS": "[]",
            "NOTIFICATION_RETENTION_DAYS": "30",
            "EVENT_RETENTION_DAYS": "90",
            "LOG_MAX_BYTES": "1048576",
            "LOG_BACKUP_COUNT": "3",
        }
    )
    from app.db import base
    from app.main import create_app
    from app.services.telemetry import collector

    collector.HEARTBEAT = 0.1
    current_server = None
    current_task = None
    try:
        current_server, current_task, port = await start_server(create_app())
        async with httpx.AsyncClient(
            trust_env=False, headers={"Authorization": f"Bearer {key}"}
        ) as http:

            async def get(path):
                response = await http.get(f"http://127.0.0.1:{port}/api/v1/telemetry{path}")
                response.raise_for_status()
                return response.json()

            async def connected():
                return (await get(""))["status"] == "connected"

            await until(connected)
            assert (await get("/history"))["total"] == 2
            await sockets[-1].send_json(
                {
                    "type": "event",
                    "id": 1,
                    "event": {
                        "event_type": "state_changed",
                        "time_fired": "2026-10-18T01:00:01Z",
                        "data": {
                            "entity_id": ENTITY,
                            "new_state": state("23", second=1),
                            "old_state": {"private": PRIVATE},
                        },
                        "context": {"user_id": PRIVATE},
                    },
                }
            )

            async def live():
                return (await get("/history"))["total"] == 3

            await until(live)
            assert (await get(""))["states"][0]["state"] == "23"
            control["offline"] = True
            await sockets[-1].close(code=1012)

            async def disconnected():
                return (await get(""))["status"] == "disconnected"

            await until(disconnected)
            assert (await get(""))["states"][0]["stale"]
            assert (await get("/gaps"))["items"][0]["ended_at"] is None
            control["states"], control["offline"] = [state("29", second=20)], False
            await until(connected)
            assert (await get(""))["states"][0]["state"] == "29"
            assert (await get(""))["states"][1]["present"] is False
            history = await get("/history")
            assert history["total"] == 5
            assert sum(row["source"] == "ha_state_changed" for row in history["items"]) == 1
            assert PRIVATE not in json.dumps(history)
            control["invalid"] = True
            await sockets[-1].close(code=1012)

            async def auth_failed():
                return (await get(""))["status"] == "auth_failed"

            await until(auth_failed)
            count = len(sockets)
            await asyncio.sleep(1.3)
            assert len(sockets) == count
            await stop_server(current_server, current_task)
            current_server, current_task = None, None
            control["invalid"] = False
            current_server, current_task, port = await start_server(create_app())
            await until(connected)
            assert (await get("/history"))["total"] == 7
            assert (await get("/gaps"))["items"][0]["ended_at"] is not None
            response = await http.get(
                f"http://127.0.0.1:{port}/api/v1/telemetry",
                headers={"Authorization": "Bearer invalid"},
            )
            assert response.status_code == 401
            assert "ping" in commands and "call_service" not in commands
        await stop_server(current_server, current_task)
        current_server, current_task = None, None
        # Реальный HTTP 302: цель перенаправления не должна получить даже handshake.
        count = len(sockets)

        async def redirect(connection, request):
            response = connection.respond(302, "redirect")
            response.headers["Location"] = f"ws://127.0.0.1:{ha_port}/api/websocket"
            return response

        async def unused(ws):
            raise AssertionError("Redirect был принят")

        async with serve(unused, "127.0.0.1", 0, process_request=redirect) as redirect_server:
            redirect_port = redirect_server.sockets[0].getsockname()[1]
            try:
                async with collector.LocalConnect(f"ws://127.0.0.1:{redirect_port}", proxy=None):
                    raise AssertionError("Ожидался отказ redirect")
            except InvalidStatus:
                pass
        assert len(sockets) == count
        await base.engine.dispose()
        for path in Path(".").rglob("*"):
            if path.is_file():
                payload = path.read_bytes()
                assert PRIVATE.encode() not in payload
                assert token.encode() not in payload
                assert key.encode() not in payload
        print("TASK-14 loopback: baseline/live/reconnect/gaps/missing/auth/restart/302/privacy OK")
    finally:
        if current_task:
            await stop_server(current_server, current_task)
        await stop_server(ha_server, ha_task)


def main():
    cache = CORE / ".pytest_cache"
    cache.mkdir(exist_ok=True)
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="task14-loopback-", dir=cache) as workspace:
        try:
            os.chdir(workspace)
            asyncio.run(scenario())
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    main()
