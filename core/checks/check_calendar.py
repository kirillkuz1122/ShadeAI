"""TASK-23: реальный HTTP Core/синтетический REPORT-сервер, без моделей/дома/внешней сети."""

import argparse
import asyncio
import base64
import json
import os
import secrets
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx
from check_telemetry import start_server, stop_server, until
from fastapi import FastAPI, Request
from fastapi.responses import Response

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))


def ical(events):
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Synthetic//EN\r\n"
        + "".join("BEGIN:VEVENT\r\n" + value + "\r\nEND:VEVENT\r\n" for value in events)
        + "END:VCALENDAR\r\n"
    )


def report(events):
    root = ET.Element("{DAV:}multistatus")
    response = ET.SubElement(root, "{DAV:}response")
    ET.SubElement(response, "{DAV:}href").text = "/calendar/synthetic/events.ics"
    propstat = ET.SubElement(response, "{DAV:}propstat")
    prop = ET.SubElement(propstat, "{DAV:}prop")
    ET.SubElement(prop, "{urn:ietf:params:xml:ns:caldav}calendar-data").text = ical(events)
    ET.SubElement(propstat, "{DAV:}status").text = "HTTP/1.1 200 OK"
    return ET.tostring(root, encoding="unicode")


async def scenario(folder):
    control = {"phase": 0, "calls": 0}
    fake = FastAPI()
    username, password = "synthetic", secrets.token_urlsafe(32)
    credential = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
    first = (
        "UID:synthetic-series\r\nDTSTART:20261019T050000Z\r\nDTEND:202610"
        "19T060000Z\r\nSUMMARY:Первая встреча"
    )
    second = (
        "UID:synthetic-series\r\nRECURRENCE-ID:20261020T050000Z\r\nDTSTAR"
        "T:20261020T050000Z\r\nDTEND:20261020T060000Z\r\nSUMMARY:Повтор в"
        "стречи"
    )
    all_day = (
        "UID:synthetic-day\r\nDTSTART;VALUE=DATE:20261021\r\nDTEND;VALUE="
        "DATE:20261022\r\nSUMMARY:Весь день"
    )

    @fake.get("/api/")
    async def ping():
        return {"message": "API running."}

    @fake.api_route("/calendar/synthetic/", methods=["REPORT"])
    async def calendar(request: Request):
        assert request.headers["Authorization"] == credential and request.headers["Depth"] == "1"
        document = ET.fromstring(await request.body())
        expand = document.find(".//{urn:ietf:params:xml:ns:caldav}expand")
        assert expand is not None and expand.attrib == {
            "start": "20261010T000000Z",
            "end": "20261220T000000Z",
        }
        control["calls"] += 1
        phase = control["phase"]
        if phase == 4:
            return Response("synthetic-unavailable", status_code=500)
        events = (
            [first, second, all_day]
            if phase == 0
            else [
                first.replace("Первая встреча", "Изменённая встреча"),
                second.replace("T050000Z\r\nDTEND", "T070000Z\r\nDTEND").replace(
                    "T060000Z", "T080000Z"
                ),
                all_day,
            ]
            if phase == 1
            else ["UID:synthetic-series\r\nSTATUS:CANCELLED", all_day]
            if phase == 2
            else []
        )
        if phase == 3:
            return Response(
                '<d:multistatus xmlns:d="DAV:"/>', status_code=207, media_type="application/xml"
            )
        return Response(report(events), status_code=207, media_type="application/xml")

    fake_server, fake_task, port = await start_server(fake)
    key = secrets.token_urlsafe(32)
    os.environ.clear()
    os.environ.update(
        SHADE_API_KEY=key,
        DB_URL=f"sqlite+aiosqlite:///{folder / 'synthetic.db'}",
        HA_BASE_URL=f"http://127.0.0.1:{port}",
        HA_TOKEN=secrets.token_urlsafe(32),
        HA_TELEMETRY_ENTITIES="[]",
        CALENDAR_URL=f"http://127.0.0.1:{port}/calendar/synthetic/",
        CALENDAR_USERNAME=username,
        CALENDAR_PASSWORD=password,
        CALENDAR_TIMEZONE="Asia/Yekaterinburg",
        LLM_ENABLED="false",
        NOTIFICATION_PROCESSOR="disabled",
        LOG_DIR=str(folder / "logs"),
    )
    from app.core import clock

    clock.utcnow = lambda: datetime(2026, 10, 19, 3, tzinfo=UTC)
    from app.db import base
    from app.main import create_app

    result = {
        "synthetic_report_server": True,
        "native_llm": False,
        "real_caldav_implementation": False,
        "hardware": False,
    }
    ids = None
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
                        data = (
                            await http.get("/api/v1/calendar/events?include_inactive=true")
                        ).json()
                        return data["status"] == ("CALENDAR_UNAVAILABLE" if cycle else "ready")

                    await until(ready)
                    if cycle:
                        data = (
                            await http.get("/api/v1/calendar/events?include_inactive=true")
                        ).json()
                        assert data["stale"] and sorted(e["id"] for e in data["events"]) == ids
                        assert data["error_code"] == "CALENDAR_UNAVAILABLE"
                        result["restart_preserves_cache"] = "PASS"
                        continue
                    assert (
                        await http.get(
                            "/api/v1/calendar/events", headers={"Authorization": "Bearer invalid"}
                        )
                    ).status_code == 401
                    data = (await http.get("/api/v1/calendar/events")).json()
                    assert not data["stale"] and data["total"] == 3
                    ids = sorted(e["id"] for e in data["events"])
                    assert any(
                        e["all_day"] and e["start_date"] == "2026-10-21" for e in data["events"]
                    )
                    control["phase"] = 1
                    assert (await http.post("/api/v1/calendar/sync")).status_code == 200
                    updated = (await http.get("/api/v1/calendar/events")).json()
                    assert sorted(e["id"] for e in updated["events"]) == ids
                    assert any(
                        e["summary"] == "Изменённая встреча" and e["revision"] == 2
                        for e in updated["events"]
                    )
                    control["phase"] = 2
                    assert (await http.post("/api/v1/calendar/sync")).status_code == 200
                    cancelled = (
                        await http.get("/api/v1/calendar/events?include_inactive=true")
                    ).json()
                    assert sum(e["status"] == "cancelled" for e in cancelled["events"]) == 2
                    control["phase"] = 3
                    assert (await http.post("/api/v1/calendar/sync")).status_code == 200
                    assert (await http.get("/api/v1/calendar/events")).json()["total"] == 0
                    control["phase"] = 4
                    assert (await http.post("/api/v1/calendar/sync")).status_code == 503
                    failed = (
                        await http.get("/api/v1/calendar/events?include_inactive=true")
                    ).json()
                    assert failed["stale"] and sorted(e["id"] for e in failed["events"]) == ids
                    assert (
                        password not in json.dumps(failed)
                        and "username" not in failed
                        and "url" not in failed
                    )
                    result.update(
                        real_core_and_report_http="PASS",
                        expanded_instances_and_dates="PASS",
                        stable_ids_update="PASS",
                        cancel_series_and_removed="PASS",
                        failure_preserves_cache="PASS",
                    )
            finally:
                await stop_server(server, task)
        result["synthetic_report_calls"] = control["calls"]
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
        prefix="task23-loopback-", dir=CORE / ".pytest_cache"
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
