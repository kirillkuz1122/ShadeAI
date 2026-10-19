"""TASK-21: настоящий loopback Core/HA WebSocket, решения/подсказка/повторный lifespan."""

import argparse
import asyncio
import json
import os
import secrets
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from check_telemetry import start_server, stop_server, until
from fastapi import FastAPI, WebSocket
from starlette.websockets import WebSocketDisconnect

CORE = Path(__file__).resolve().parents[1]
ENTITY = "binary_sensor.synthetic_presence"
LIGHT = "light.synthetic_entry"
PRIVATE = "private-synthetic-context-not-for-hint"
sys.path.insert(0, str(CORE))


async def scenario(folder):
    ha = FastAPI()
    token = secrets.token_urlsafe(32)
    sockets = []
    commands = []

    def state(value):
        now = datetime.now(UTC).isoformat()
        return {
            "entity_id": ENTITY,
            "state": value,
            "last_changed": now,
            "last_updated": now,
            "attributes": {"private": PRIVATE},
        }

    @ha.get("/api/")
    async def ping():
        return {"message": "API running."}

    @ha.post("/api/services/{domain}/{service}")
    async def command(domain: str, service: str):
        commands.append([domain, service])
        return []

    @ha.websocket("/api/websocket")
    async def websocket(ws: WebSocket):
        await ws.accept()
        sockets.append(ws)
        try:
            await ws.send_json({"type": "auth_required"})
            auth = await ws.receive_json()
            assert auth == {"type": "auth", "access_token": token}
            await ws.send_json({"type": "auth_ok"})
            while True:
                request = await ws.receive_json()
                if request["type"] == "ping":
                    await ws.send_json({"id": request["id"], "type": "pong"})
                else:
                    assert request["type"] in {"subscribe_events", "get_states"}
                    result = [state("off")] if request["type"] == "get_states" else None
                    await ws.send_json(
                        {"id": request["id"], "type": "result", "success": True, "result": result}
                    )
        except WebSocketDisconnect:
            pass
        finally:
            sockets.remove(ws)

    fake, fake_task, ha_port = await start_server(ha)
    key = secrets.token_urlsafe(32)
    os.environ.clear()
    os.environ.update(
        {
            "SHADE_API_KEY": key,
            "DB_URL": f"sqlite+aiosqlite:///{folder / 'synthetic.db'}",
            "HA_BASE_URL": f"http://127.0.0.1:{ha_port}",
            "HA_TOKEN": token,
            "HA_TELEMETRY_ENTITIES": json.dumps([ENTITY]),
            "ANALYTICS_PRESENCE_ENTITY": ENTITY,
            "ANALYTICS_TIMEZONE": "UTC",
            "AUTOMATION_ALLOWED_LIGHTS": json.dumps([LIGHT]),
            "SUGGESTIONS_INTERVAL_SECONDS": "5",
            "LLM_ENABLED": "false",
            "NOTIFICATION_PROCESSOR": "disabled",
            "LOG_DIR": str(folder / "logs"),
        }
    )
    from app import main
    from app.db import base
    from app.db.models import NotificationRaw, SensorHistory, TelemetryCheckpoint
    from app.schemas import NotificationIn
    from app.services.notification.store import identity
    from app.services.telemetry.store import naive

    await base.init_db()
    now = datetime.now(UTC)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=28)
    async with base.async_session() as session, session.begin():
        session.add(
            SensorHistory(
                entity_id=ENTITY,
                state="on",
                source="ha_snapshot",
                attributes_json="{}",
                observed_at=naive(start),
            )
        )
        for day in range(28):
            for hour, value in ((8, "off"), (18, "on")):
                stamp = start + timedelta(days=day, hours=hour)
                session.add(
                    SensorHistory(
                        entity_id=ENTITY,
                        state=value,
                        source="ha_state_changed",
                        attributes_json="{}",
                        observed_at=naive(stamp),
                        ha_timestamp=naive(stamp),
                    )
                )
        await session.merge(TelemetryCheckpoint(id=1, last_seen=naive(now)))
        payload = {
            "processor": "llm",
            "llm": True,
            "schema_version": 1,
            "category": "delivery",
            "priority": "default",
            "intent": "delivery_event",
            "entities": {"subject": PRIVATE, "location": None, "service": None},
            "time": {
                "source": None,
                "timezone": "UTC",
                "at": None,
                "date": None,
                "resolution": "absent",
            },
            "action_authorized": False,
        }
        admitted = NotificationIn(
            app_name="ru.ozon.app.android",
            title="Синтетический контекст",
            text=PRIVATE,
            timestamp=now.isoformat(),
            priority="default",
        )
        dedupe_key, payload_hash = identity(admitted)
        session.add(
            NotificationRaw(
                app_name="ru.ozon.app.android",
                title="Синтетический контекст",
                text=PRIVATE,
                timestamp=admitted.timestamp,
                dedupe_key=dedupe_key,
                payload_hash=payload_hash,
                priority="default",
                category="delivery",
                is_processed=1,
                processing_status="processed",
                extracted_data_json=json.dumps(payload),
                created_at=naive(now),
            )
        )
    report = {
        "synthetic": True,
        "context": "seeded-valid-LLM-schema-not-native-inference",
        "runs": [],
    }
    expected_ids = None
    feed_id = None
    try:
        for cycle in range(2):
            server, task, port = await start_server(main.create_app())
            try:
                async with httpx.AsyncClient(
                    base_url=f"http://127.0.0.1:{port}",
                    headers={"Authorization": f"Bearer {key}"},
                    trust_env=False,
                    timeout=3,
                ) as http:

                    async def ready():
                        body = (await http.get("/api/v1/health")).json()
                        return body["services"]["analytics"] == "ready" and body["ha_connected"]

                    await until(ready)
                    assert (await http.post("/api/v1/automations/refresh")).status_code == 200
                    data = (await http.get("/api/v1/automations")).json()
                    ids = sorted(row["id"] for row in data["automations"])
                    assert len(ids) == 4
                    if expected_ids is not None:
                        assert ids == expected_ids
                    expected_ids = ids
                    arrival = next(
                        row
                        for row in data["automations"]
                        if row["trigger"]["kind"] == "arrival_home"
                        and row["trigger"]["day_group"] == "weekdays"
                    )
                    departure = next(
                        row
                        for row in data["automations"]
                        if row["trigger"]["kind"] == "departure_home"
                        and row["trigger"]["day_group"] == "weekdays"
                    )
                    if cycle == 0:
                        response = await http.post(
                            f"/api/v1/automations/{arrival['id']}/decision",
                            json={
                                "decision": "accept",
                                "version": arrival["version"],
                                "target_entity": LIGHT,
                            },
                        )
                        assert (
                            response.status_code == 200
                            and response.json()["approval_valid"]
                            and not response.json()["executable"]
                        )
                        rejected = await http.post(
                            f"/api/v1/automations/{departure['id']}/decision",
                            json={"decision": "reject", "version": departure["version"]},
                        )
                        assert rejected.status_code == 200
                    else:
                        assert arrival["status"] == "accepted" and arrival["approval_valid"]
                        assert departure["status"] == "rejected"
                    before = (await http.get("/api/v1/hints")).json()
                    if feed_id is None:
                        feed_id = before["feed_id"]
                    assert before["feed_id"] == feed_id
                    event_state = state("on")
                    await sockets[-1].send_json(
                        {
                            "id": 1,
                            "type": "event",
                            "event": {
                                "event_type": "state_changed",
                                "time_fired": event_state["last_updated"],
                                "data": {
                                    "entity_id": ENTITY,
                                    "new_state": event_state,
                                    "old_state": state("off"),
                                },
                                "context": {"user_id": PRIVATE},
                            },
                        }
                    )

                    async def live():
                        telemetry = (await http.get("/api/v1/telemetry")).json()
                        return telemetry["states"][0]["state"] == "on"

                    await until(live)
                    assert (await http.post("/api/v1/automations/refresh")).status_code == 200
                    hints = (await http.get("/api/v1/hints")).json()
                    assert (
                        len(hints["hints"]) == 1 and hints["hints"][0]["kind"] == "arrival_delivery"
                    )
                    assert PRIVATE not in json.dumps(hints)
                    assert (
                        await http.get("/api/v1/hints", headers={"Authorization": "Bearer invalid"})
                    ).status_code == 401
                    report["runs"].append(
                        {
                            "rules": len(ids),
                            "arrival_status": arrival["status"] if cycle else "accepted",
                            "hints": len(hints["hints"]),
                            "feed_stable": hints["feed_id"] == feed_id,
                            "telemetry_state": "on",
                            "native_llm": False,
                        }
                    )
            finally:
                await stop_server(server, task)
        assert commands == []
        report.update(
            http_and_real_ha_websocket="PASS",
            restart_and_sticky_decisions="PASS",
            arrival_context_no_repeat="PASS",
            ha_commands=0,
        )
        return report
    finally:
        await stop_server(fake, fake_task)
        await base.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    output = parser.parse_args().output.resolve()
    if output.exists():
        parser.error("Выберите новый output, существующий отчёт не перезаписывается")
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(
        prefix="task21-loopback-", dir=CORE / ".pytest_cache"
    ) as scratch:
        folder = Path(scratch)
        os.chdir(folder)
        try:
            report = asyncio.run(scenario(folder))
        finally:
            os.chdir(previous)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
