"""TASK-24: HTTP Core + синтетические CalDAV/HA, reminders и пересекающиеся встречи."""

import argparse
import asyncio
import json
import os
import secrets
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
from check_calendar import report
from check_telemetry import start_server, stop_server, until
from fastapi import FastAPI, Request
from fastapi.responses import Response

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))
ENTITY = "switch.synthetic_dnd"


async def scenario(folder):
    now = [datetime(2026, 10, 19, 3, tzinfo=UTC)]
    fake = FastAPI()
    control = {"offline": False, "state": "off", "context": "synthetic_initial", "commands": []}
    token, key = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    first = (
        "UID:synthetic-a\r\nDTSTART:20261019T050000Z\r\nDTEND:20261019T060000Z\r\nSUMMARY:Встреча А"
    )
    second = (
        "UID:synthetic-b\r\nDTSTART:20261019T053000Z\r\nDTEND:20261019T063000Z\r\nSUMMARY:Встреча Б"
    )

    def state():
        return dict(
            entity_id=ENTITY,
            state=control["state"],
            attributes={},
            context={"id": control["context"], "user_id": "synthetic-private-ha-user"},
            last_changed=control.get("changed", now[0].isoformat()),
            last_updated=control.get("changed", now[0].isoformat()),
        )

    @fake.get("/api/")
    async def ping():
        return {"message": "API running."}

    @fake.get("/api/states/{entity}")
    async def current(entity: str, request: Request):
        assert entity == ENTITY and request.headers["Authorization"] == f"Bearer {token}"
        return state()

    @fake.post("/api/services/switch/{service}")
    async def command(service: str, request: Request):
        assert service in {"turn_on", "turn_off"} and await request.json() == {"entity_id": ENTITY}
        assert request.headers["Authorization"] == f"Bearer {token}"
        control["commands"].append(service)
        control["state"] = "on" if service == "turn_on" else "off"
        control["context"] = "synthetic_command_" + str(len(control["commands"]))
        control["changed"] = now[0].isoformat()
        return [state()]

    @fake.api_route("/calendar/synthetic/", methods=["REPORT"])
    async def calendar():
        return (
            Response("unavailable", status_code=500)
            if control["offline"]
            else Response(report([first, second]), status_code=207, media_type="application/xml")
        )

    fake_server, fake_task, port = await start_server(fake)
    os.environ.clear()
    os.environ.update(
        SHADE_API_KEY=key,
        DB_URL=f"sqlite+aiosqlite:///{folder / 'synthetic.db'}",
        HA_BASE_URL=f"http://127.0.0.1:{port}",
        HA_TOKEN=token,
        HA_TELEMETRY_ENTITIES="[]",
        CALENDAR_URL=f"http://127.0.0.1:{port}/calendar/synthetic/",
        CALENDAR_TIMEZONE="UTC",
        CALENDAR_REMINDERS_ENABLED="true",
        MEETING_MODE_ENABLED="true",
        MEETING_MODE_ALLOWED_SWITCHES=json.dumps([ENTITY]),
        LLM_ENABLED="false",
        NOTIFICATION_PROCESSOR="disabled",
        LOG_DIR=str(folder / "logs"),
    )
    from app.core import clock

    clock.utcnow = lambda: now[0]
    from app.db import base
    from app.main import create_app

    result = dict(synthetic=True, hardware=False, native_llm=False)
    try:
        for cycle in range(2):
            app = create_app()
            server, task, core_port = await start_server(app)
            try:
                async with httpx.AsyncClient(
                    base_url=f"http://127.0.0.1:{core_port}",
                    headers={"Authorization": f"Bearer {key}"},
                    trust_env=False,
                    timeout=3,
                ) as http:

                    async def ready(cycle=cycle):
                        data = (await http.get("/api/v1/calendar/events")).json()
                        return data["status"] == ("CALENDAR_UNAVAILABLE" if cycle else "ready")

                    await until(ready)
                    if cycle:
                        await app.state.meeting.tick()
                        assert control["commands"] == ["turn_on", "turn_off"]
                        data = (await http.get("/api/v1/calendar/meeting")).json()
                        assert data["leases"][0]["state"] == "completed"
                        result["restart_no_replay"] = "PASS"
                        continue
                    events = (await http.get("/api/v1/calendar/events")).json()["events"]
                    assert len(events) == 2
                    for event in events:
                        url = f"/api/v1/calendar/events/{event['id']}/meeting"
                        view = (await http.get(url)).json()
                        accepted = await http.post(
                            url,
                            json=dict(
                                decision="approve",
                                event_revision=event["revision"],
                                policy_scope=view["policy_scope"],
                                targets=[ENTITY],
                            ),
                        )
                        assert accepted.status_code == 200
                    schedule = (await http.get("/api/v1/calendar/reminders")).json()
                    assert len(schedule["reminders"]) == 2 and not schedule["reminders"][0]["due"]
                    reminder = schedule["reminders"][0]["id"]
                    now[0] = now[0].replace(hour=4, minute=50)
                    assert (await http.post("/api/v1/calendar/sync")).status_code == 200
                    assert (await http.get(f"/api/v1/calendar/reminders/{reminder}")).json()[
                        "reminder"
                    ]["due"]
                    now[0] = now[0].replace(hour=4, minute=56)
                    await http.post("/api/v1/calendar/sync")
                    assert (
                        await http.get(f"/api/v1/calendar/reminders/{reminder}")
                    ).status_code == 404
                    for hour, minute, members in [(5, 0, 1), (5, 30, 2), (6, 0, 1)]:
                        now[0] = now[0].replace(hour=hour, minute=minute)
                        await http.post("/api/v1/calendar/sync")
                        await app.state.meeting.tick()
                        data = (await http.get("/api/v1/calendar/meeting")).json()
                        assert (
                            data["leases"][0]["state"] == "active"
                            and len(data["leases"][0]["members"]) == members
                        )
                        assert control["commands"] == ["turn_on"]
                    now[0] = now[0].replace(hour=6, minute=30)
                    control["offline"] = True
                    assert (await http.post("/api/v1/calendar/sync")).status_code == 503
                    await app.state.meeting.tick()
                    data = (await http.get("/api/v1/calendar/meeting")).json()
                    assert (
                        data["leases"][0]["reason"] == "RESTORE_OBSERVED"
                        and control["state"] == "off"
                    )
                    assert "synthetic-private-ha-user" not in json.dumps(data)
                    assert (
                        await http.get(
                            "/api/v1/calendar/meeting", headers={"Authorization": "Bearer invalid"}
                        )
                    ).status_code == 401
                    result.update(
                        reminder_due_and_expiry="PASS",
                        explicit_consent="PASS",
                        overlap_single_lease="PASS",
                        stale_stored_end_restore="PASS",
                        audit_and_privacy="PASS",
                    )
            finally:
                await stop_server(server, task)
        for file in folder.glob("synthetic.db*"):
            assert b"synthetic-private-ha-user" not in file.read_bytes()
        result["synthetic_ha_commands"] = control["commands"]
        return result
    finally:
        await stop_server(fake_server, fake_task)
        await base.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    output = parser.parse_args().output.resolve()
    if output.exists():
        parser.error("Существующий отчёт не перезаписывается")
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(
        prefix="task24-loopback-", dir=CORE / ".pytest_cache"
    ) as folder:
        os.chdir(folder)
        try:
            result = asyncio.run(scenario(Path(folder)))
        finally:
            os.chdir(previous)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
