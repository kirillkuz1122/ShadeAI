"""TASK-23: настоящий Xandikos/Core на loopback, только синтетическая коллекция."""

import argparse
import asyncio
import importlib.metadata
import json
import os
import platform
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
from check_telemetry import start_server, stop_server, until

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))


def ical(*events):
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Shade Synthetic QA//EN\r\n"
        + "".join(
            "BEGIN:VEVENT\r\nDTSTAMP:20261020T030000Z\r\n" + e + "\r\nEND:VEVENT\r\n"
            for e in events
        )
        + "END:VCALENDAR\r\n"
    ).encode()


async def scenario(folder, dependencies):
    assert shutil.disk_usage(CORE).free >= 4 * 1024**3
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    calendar_url = f"http://127.0.0.1:{port}/user/calendars/calendar/"
    env = {"PATH": os.defpath, "LANG": "C.UTF-8", "PYTHONPATH": str(dependencies)}
    log = (folder / "xandikos.log").open("wb")
    key = secrets.token_urlsafe(32)
    os.environ.update(
        SHADE_API_KEY=key,
        DB_URL=f"sqlite+aiosqlite:///{folder / 'core.db'}",
        HA_BASE_URL="http://127.0.0.1:1",
        HA_TOKEN="",
        HA_TELEMETRY_ENTITIES="[]",
        CALENDAR_URL=calendar_url,
        CALENDAR_USERNAME="",
        CALENDAR_PASSWORD="",
        CALENDAR_TIMEZONE="Asia/Yekaterinburg",
        CALENDAR_INTERVAL_SECONDS="3600",
        CALENDAR_REMINDERS_ENABLED="false",
        MEETING_ENABLED="false",
        LLM_ENABLED="false",
        VOICE_ENABLED="false",
        ACCESS_ENABLED="false",
        NOTIFICATION_PROCESSOR="disabled",
        LOG_DIR=str(folder / "logs"),
    )
    from app.core import clock
    from app.db import base
    from app.main import create_app
    from app.services.calendar.service import report_xml

    clock.utcnow = lambda: datetime(2026, 10, 20, 3, tzinfo=UTC)
    result = dict(
        real_caldav_implementation=True,
        real_core=True,
        xandikos="0.4.10",
        synthetic_calendar=True,
        physical_phone=False,
        pi=False,
        native_llm=False,
        actual_ha=False,
        authentication_tested=False,
        fixed_core_clock="2026-10-20T03:00:00.000000Z",
        checks=[],
    )
    series = (
        "UID:fixture-series\r\nDTSTART:20261021T050000Z\r\nDTEND:20261021T060000Z\r\n"
        "RRULE:FREQ=DAILY;COUNT=4\r\nEXDATE:20261022T050000Z\r\nRDATE:20261025T050000Z\r\n"
        "SUMMARY:Синтетическая серия\r\nDESCRIPTION:synthetic-private-description"
    )
    moved = (
        "UID:fixture-series\r\nRECURRENCE-ID:20261023T050000Z\r\n"
        "DTSTART:20261023T073000Z\r\nDTEND:20261023T083000Z\r\nSUMMARY:Перенесённый повтор"
    )
    day = (
        "UID:fixture-day\r\nDTSTART;VALUE=DATE:20261026\r\n"
        "DTEND;VALUE=DATE:20261027\r\nSUMMARY:Весь день"
    )
    dst = (
        "UID:fixture-dst\r\nDTSTART;TZID=Europe/Berlin:20261024T090000\r\n"
        "DTEND;TZID=Europe/Berlin:20261024T100000\r\n"
        "RRULE:FREQ=DAILY;COUNT=3\r\nSUMMARY:Переход DST"
    )
    floating = (
        "UID:fixture-floating\r\nDTSTART:20261027T100000\r\n"
        "DURATION:PT1H\r\nSUMMARY:Локальное время"
    )
    child = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "xandikos",
            "serve",
            "-d",
            str(folder / "dav"),
            "--state-dir",
            str(folder / "state"),
            "--defaults",
            "-l",
            "127.0.0.1",
            "-p",
            str(port),
            "--no-detect-systemd",
            "--imip-send",
            "off",
        ],
        env=env,
        cwd=folder,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=5) as dav:

            async def ready():
                assert child.poll() is None, "Xandikos остановился до проверки"
                try:
                    return (await dav.request("OPTIONS", calendar_url)).status_code == 200
                except httpx.ConnectError:
                    return False

            await until(ready, timeout=15)
            for name, data in {
                "series": ical(series, moved),
                "day": ical(day),
                "dst": ical(dst),
                "floating": ical(floating),
            }.items():
                response = await dav.put(
                    calendar_url + name + ".ics",
                    content=data,
                    headers={"Content-Type": "text/calendar"},
                )
                assert response.status_code == 201, (name, response.status_code)
            response = await dav.request(
                "REPORT",
                calendar_url,
                content=report_xml(
                    datetime(2026, 10, 11, tzinfo=UTC), datetime(2026, 12, 21, tzinfo=UTC)
                ),
                headers={"Depth": "1", "Content-Type": "application/xml"},
            )
            assert response.status_code == 207
            (CORE / ".pytest_cache/task23-caldav-last-report.xml").write_bytes(response.content)
            result["checks"].append("PUT and REPORT on real server")
            ids = None
            for cycle in range(2):
                app = create_app()
                server, task, core_port = await start_server(app)
                try:
                    async with httpx.AsyncClient(
                        base_url=f"http://127.0.0.1:{core_port}/api/v1",
                        headers={"Authorization": "Bearer " + key},
                        trust_env=False,
                        timeout=8,
                    ) as core:

                        async def synced():
                            page = (await core.get("/calendar/events?include_inactive=true")).json()
                            if page["error_code"]:
                                raise AssertionError(page["error_code"])
                            return page["status"] == "ready"

                        await until(synced)
                        page = (await core.get("/calendar/events")).json()
                        if cycle:
                            assert sorted(e["id"] for e in page["events"]) == ids
                            result["checks"].append("restart stable IDs and cache")
                            continue
                        assert page["total"] == 9, page["total"]
                        events = page["events"]
                        assert sorted(
                            e["starts_at"] for e in events if "серия" in e["summary"]
                        ) == [
                            "2026-10-21T05:00:00.000000Z",
                            "2026-10-24T05:00:00.000000Z",
                            "2026-10-25T05:00:00.000000Z",
                        ]
                        assert (
                            next(e for e in events if e["summary"] == "Перенесённый повтор")[
                                "starts_at"
                            ]
                            == "2026-10-23T07:30:00.000000Z"
                        )
                        assert sorted(
                            e["starts_at"] for e in events if e["summary"] == "Переход DST"
                        ) == [
                            "2026-10-24T07:00:00.000000Z",
                            "2026-10-25T08:00:00.000000Z",
                            "2026-10-26T08:00:00.000000Z",
                        ]
                        all_day = next(e for e in events if e["all_day"])
                        assert (all_day["start_date"], all_day["end_date"]) == (
                            "2026-10-26",
                            "2026-10-27",
                        )
                        assert (
                            next(e for e in events if e["summary"] == "Локальное время")[
                                "starts_at"
                            ]
                            == "2026-10-27T05:00:00.000000Z"
                        )
                        result["checks"].append(
                            "RRULE EXDATE RDATE override DATE floating IANA DST"
                        )
                        original = {e["id"]: e["revision"] for e in events}
                        assert (await core.post("/calendar/sync")).status_code == 200
                        assert {
                            e["id"]: e["revision"]
                            for e in (await core.get("/calendar/events")).json()["events"]
                        } == original
                        response = await dav.put(
                            calendar_url + "series.ics",
                            content=ical(
                                series,
                                moved.replace("T073000Z", "T093000Z").replace(
                                    "T083000Z", "T103000Z"
                                ),
                            ),
                            headers={"Content-Type": "text/calendar"},
                        )
                        assert response.status_code in {201, 204}
                        assert (await core.post("/calendar/sync")).status_code == 200
                        changed = (await core.get("/calendar/events")).json()["events"]
                        row = next(e for e in changed if e["summary"] == "Перенесённый повтор")
                        assert (
                            row["id"] in original
                            and row["revision"] == original[row["id"]] + 1
                            and row["starts_at"] == "2026-10-23T09:30:00.000000Z"
                        )
                        assert (
                            await dav.put(
                                calendar_url + "day.ics",
                                content=ical(day + "\r\nSTATUS:CANCELLED"),
                                headers={"Content-Type": "text/calendar"},
                            )
                        ).status_code == 204
                        assert (await dav.delete(calendar_url + "floating.ics")).status_code == 204
                        assert (await core.post("/calendar/sync")).status_code == 200
                        page = (await core.get("/calendar/events?include_inactive=true")).json()
                        assert sum(e["status"] == "cancelled" for e in page["events"]) == 1
                        assert sum(e["status"] == "removed" for e in page["events"]) == 1
                        ids = sorted(e["id"] for e in page["events"] if e["status"] == "confirmed")
                        result["checks"].append("stable revision update cancelled removed")
                        assert "synthetic-private-description" not in json.dumps(page)
                        assert (await core.get("/events")).json()["total"] == 0
                finally:
                    await stop_server(server, task)
            child.terminate()
            child.wait(timeout=5)
            app = create_app()
            server, task, core_port = await start_server(app)
            try:
                async with httpx.AsyncClient(
                    base_url=f"http://127.0.0.1:{core_port}/api/v1",
                    headers={"Authorization": "Bearer " + key},
                    trust_env=False,
                ) as core:

                    async def failed():
                        return (await core.get("/calendar/events")).json()[
                            "status"
                        ] == "CALENDAR_UNAVAILABLE"

                    await until(failed)
                    page = (await core.get("/calendar/events")).json()
                    assert page["stale"] and sorted(e["id"] for e in page["events"]) == ids
                    result["checks"].append("server down restart keeps stale cache")
            finally:
                await stop_server(server, task)
        result["result"] = "PASS"
        return result
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        log.close()
        await base.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dependencies", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    dependencies = args.dependencies.resolve()
    if output.exists():
        parser.error("Существующий отчёт не перезаписывается")
    assert (dependencies / "xandikos").is_dir()
    versions = {
        d.metadata["Name"]: d.version
        for d in importlib.metadata.distributions(path=[str(dependencies)])
    }
    assert versions.get("xandikos") == "0.4.10", "Стенд закреплён за Xandikos0.4.10"
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(
        prefix="task23-xandikos-", dir=CORE / ".pytest_cache"
    ) as folder:
        os.chdir(folder)
        try:
            result = asyncio.run(scenario(Path(folder), dependencies))
        finally:
            os.chdir(previous)
    result.update(
        fixture_packages=versions, python=platform.python_version(), machine=platform.machine()
    )
    with output.open("x") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
