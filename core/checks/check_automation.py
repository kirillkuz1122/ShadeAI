"""TASK-22: настоящий loopback Core + синтетический HA REST/WS, без моделей/дома."""

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
from fastapi import FastAPI, Request, WebSocket
from starlette.websockets import WebSocketDisconnect

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))
PRIMARY, HOME, LIGHT = (
    "binary_sensor.synthetic_person",
    "binary_sensor.synthetic_house",
    "light.synthetic_entry",
)


async def scenario(folder):
    stamp = [datetime(2026, 11, 12, 18, tzinfo=UTC)]
    token, key = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    sockets, commands = [], []
    values = {PRIMARY: "off", HOME: "off"}
    fake = FastAPI()

    def state(entity, value):
        return dict(
            entity_id=entity,
            state=value,
            attributes={},
            last_changed=stamp[0].isoformat(),
            last_updated=stamp[0].isoformat(),
        )

    @fake.get("/api/")
    async def ping(request: Request):
        assert request.headers["Authorization"] == f"Bearer {token}"
        return {"message": "API running."}

    @fake.post("/api/services/light/turn_on")
    async def command(request: Request):
        assert request.headers["Authorization"] == f"Bearer {token}"
        assert await request.json() == {"entity_id": LIGHT}
        commands.append("light.turn_on")
        return []

    @fake.get("/api/states/{entity}")
    async def light(entity: str):
        assert entity == LIGHT
        return state(LIGHT, "on")

    @fake.websocket("/api/websocket")
    async def websocket(ws: WebSocket):
        await ws.accept()
        sockets.append(ws)
        try:
            await ws.send_json({"type": "auth_required"})
            assert await ws.receive_json() == {"type": "auth", "access_token": token}
            await ws.send_json({"type": "auth_ok"})
            while True:
                request = await ws.receive_json()
                if request["type"] == "ping":
                    await ws.send_json({"id": request["id"], "type": "pong"})
                else:
                    assert request["type"] in {"subscribe_events", "get_states"}
                    result = (
                        [state(e, v) for e, v in values.items()]
                        if request["type"] == "get_states"
                        else None
                    )
                    await ws.send_json(
                        dict(id=request["id"], type="result", success=True, result=result)
                    )
        except WebSocketDisconnect:
            pass
        finally:
            sockets.remove(ws)

    server, task, port = await start_server(fake)
    os.environ.clear()
    os.environ.update(
        SHADE_API_KEY=key,
        DB_URL=f"sqlite+aiosqlite:///{folder / 'synthetic.db'}",
        HA_BASE_URL=f"http://127.0.0.1:{port}",
        HA_TOKEN=token,
        HA_TELEMETRY_ENTITIES=json.dumps([PRIMARY, HOME]),
        ANALYTICS_PRESENCE_ENTITY=PRIMARY,
        ANALYTICS_TIMEZONE="UTC",
        AUTOMATION_ALLOWED_LIGHTS=json.dumps([LIGHT]),
        AUTOMATION_EXECUTION_ENABLED="true",
        AUTOMATION_HOME_PRESENCE_ENTITY=HOME,
        AUTOMATION_CANCEL_SECONDS="10",
        SUGGESTIONS_INTERVAL_SECONDS="5",
        LLM_ENABLED="false",
        NOTIFICATION_PROCESSOR="disabled",
        LOG_DIR=str(folder / "logs"),
    )
    from app.core import clock

    clock.utcnow = lambda: stamp[0]
    from app.db import base
    from app.db.models import SensorHistory, TelemetryCheckpoint
    from app.main import create_app
    from app.services.telemetry.store import naive

    await base.init_db()
    start = stamp[0].replace(hour=0) - timedelta(days=28)
    async with base.async_session() as session, session.begin():
        session.add(
            SensorHistory(
                entity_id=PRIMARY,
                state="on",
                source="ha_snapshot",
                attributes_json="{}",
                observed_at=naive(start),
            )
        )
        for day in range(28):
            for hour, value in ((8, "off"), (18, "on")):
                at = start + timedelta(days=day, hours=hour)
                session.add(
                    SensorHistory(
                        entity_id=PRIMARY,
                        state=value,
                        source="ha_state_changed",
                        attributes_json="{}",
                        observed_at=naive(at),
                        ha_timestamp=naive(at),
                    )
                )

        await session.merge(TelemetryCheckpoint(id=1, last_seen=naive(stamp[0])))

    async def transition(http, value):
        stamp[0] += timedelta(seconds=1)
        for entity in (PRIMARY, HOME):
            values[entity] = value
            await sockets[-1].send_json(
                dict(
                    id=1,
                    type="event",
                    event=dict(
                        event_type="state_changed",
                        time_fired=stamp[0].isoformat(),
                        data=dict(entity_id=entity, new_state=state(entity, value)),
                    ),
                )
            )

        async def live():
            body = (await http.get("/api/v1/telemetry")).json()
            return len(body["states"]) == 2 and all(row["state"] == value for row in body["states"])

        await until(live)

    report = {"synthetic": True, "native_llm": False, "hardware": False}
    try:
        for cycle in range(2):
            app = create_app()
            core_server, core_task, core_port = await start_server(app)
            try:
                async with httpx.AsyncClient(
                    base_url=f"http://127.0.0.1:{core_port}",
                    trust_env=False,
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=3,
                ) as http:

                    async def ready(app=app):
                        body = (await http.get("/api/v1/health")).json()
                        return (
                            body["ha_connected"]
                            and body["services"]["analytics"] == "ready"
                            and app.state.telemetry.status == "connected"
                        )

                    await until(ready)
                    await http.post("/api/v1/automations/refresh")
                    if cycle:
                        data = (await http.get("/api/v1/automations/runs")).json()["runs"]
                        assert any(row["state"] == "succeeded" for row in data)
                        await app.state.automation_executor.tick()
                        assert len(commands) == 1
                        report["restart_no_replay"] = "PASS"
                        continue
                    proposals = (await http.get("/api/v1/automations")).json()["automations"]
                    rule = next(
                        row
                        for row in proposals
                        if row["trigger"]["kind"] == "arrival_home"
                        and row["trigger"]["day_group"] == "weekdays"
                    )
                    accepted = await http.post(
                        f"/api/v1/automations/{rule['id']}/decision",
                        json=dict(
                            decision="accept",
                            version=rule["version"],
                            target_entity=LIGHT,
                            approval_scope=rule["approval_scope"],
                        ),
                    )
                    assert accepted.status_code == 200 and accepted.json()["executable"]
                    await transition(http, "on")
                    await app.state.automation_executor.tick()
                    row = (await http.get("/api/v1/automations/runs")).json()["runs"][0]
                    assert row["state"] == "pending" and not commands
                    assert (
                        await http.post(f"/api/v1/automations/runs/{row['id']}/cancel")
                    ).status_code == 200
                    await transition(http, "off")
                    await transition(http, "on")
                    await app.state.automation_executor.tick()
                    stamp[0] += timedelta(seconds=11)
                    await app.state.automation_executor.tick()
                    data = (await http.get("/api/v1/automations/runs")).json()["runs"]
                    assert (
                        data[0]["state"] == "succeeded"
                        and data[0]["event_id"] is not None
                        and commands == ["light.turn_on"]
                    )
                    assert data[1]["reason"] == "USER_CANCELLED"
                    await transition(http, "off")
                    await transition(http, "on")
                    await app.state.automation_executor.tick()
                    stamp[0] += timedelta(seconds=11)
                    await app.state.automation_executor.tick()
                    data = (await http.get("/api/v1/automations/runs")).json()["runs"]
                    assert data[0]["reason"] == "COOLDOWN" and len(commands) == 1
                    assert (
                        await http.get(
                            "/api/v1/automations/runs", headers={"Authorization": "Bearer invalid"}
                        )
                    ).status_code == 401
                    report.update(
                        http_and_ha_rest_ws="PASS",
                        manual_cancel="PASS",
                        cooldown="PASS",
                        audit_link="PASS",
                    )
            finally:
                await stop_server(core_server, core_task)
        report["synthetic_ha_commands"] = len(commands)
        return report
    finally:
        await stop_server(server, task)
        await base.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    output = parser.parse_args().output.resolve()
    if output.exists():
        parser.error("Существующий отчёт не перезаписывается")
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(
        prefix="task22-loopback-", dir=CORE / ".pytest_cache"
    ) as folder:
        os.chdir(folder)
        try:
            report = asyncio.run(scenario(Path(folder)))
        finally:
            os.chdir(previous)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
