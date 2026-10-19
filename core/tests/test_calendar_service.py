import asyncio
from datetime import UTC, datetime, timedelta
from xml.etree import ElementTree as ET

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core import clock
from app.core.config import Settings, settings
from app.db import base
from app.db.models import CalendarEvent
from app.services.calendar.codec import CalendarError
from app.services.calendar.service import CalendarService
from tests.test_calendar_codec import BASE, ical, report

NOW = datetime(2026, 10, 19, 3, tzinfo=UTC)


@pytest.fixture
def calendar(client, monkeypatch, ha_mock):
    monkeypatch.setattr(clock, "utcnow", lambda: NOW)
    monkeypatch.setattr(settings, "calendar_url", "http://127.0.0.1:8533/calendar/synthetic/")
    monkeypatch.setattr(settings, "calendar_username", "synthetic")
    monkeypatch.setattr(settings, "calendar_password", "test-password")
    service = CalendarService()
    client.app.state.calendar = service
    ha_mock.calendar_xml = report(ical(BASE))
    yield service
    client.portal.call(service.close)


def read(client, headers, **params):
    response = client.get("/api/v1/calendar/events", headers=headers, params=params)
    assert response.status_code == 200
    return response.json()


def test_default_disabled_protected_empty_and_no_network(client, auth_headers, ha_mock):
    assert client.get("/api/v1/calendar/events").status_code == 401
    assert client.post("/api/v1/calendar/sync").status_code == 401
    assert client.post("/api/v1/calendar/sync", headers=auth_headers).json() == {
        "status": "disabled"
    }
    data = read(client, auth_headers)
    assert data["events"] == [] and data["status"] == "disabled" and not data["configured"]
    assert not any(r.method == "REPORT" for r in ha_mock.requests)


def test_sync_update_delete_cancellation_and_no_private_columns(
    client, auth_headers, calendar, ha_mock
):
    assert client.post("/api/v1/calendar/sync", headers=auth_headers).status_code == 200
    first = read(client, auth_headers)
    assert not first["stale"] and first["total"] == 1 and first["events"][0]["summary"] == "Встреча"
    row = first["events"][0]
    client.portal.call(calendar.sync)
    assert read(client, auth_headers)["events"][0]["revision"] == 1
    ha_mock.calendar_xml = report(
        ical(
            BASE.replace("Встреча", "Изменение")
            .replace("20261019T050000Z", "20261019T070000Z")
            .replace("20261019T060000Z", "20261019T080000Z")
        )
    )
    client.portal.call(calendar.sync)
    updated = read(client, auth_headers)["events"][0]
    assert (
        updated["id"] == row["id"]
        and updated["revision"] == 2
        and updated["summary"] == "Изменение"
    )
    ha_mock.calendar_xml = report(ical("UID:synthetic-one\r\nSTATUS:CANCELLED"))
    client.portal.call(calendar.sync)
    assert read(client, auth_headers)["events"] == []
    old = read(client, auth_headers, include_inactive=True)["events"][0]
    assert old["status"] == "cancelled" and not old["busy"] and old["revision"] == 3
    assert (
        client.get(f"/api/v1/calendar/events/{row['id']}", headers=auth_headers).json()["event"][
            "status"
        ]
        == "cancelled"
    )
    assert not {"description", "attendees", "uid", "password", "url"} & row.keys()
    assert all("private" not in key for key in CalendarEvent.__table__.columns.keys())


def test_successful_missing_is_removed_not_claimed_cancelled(
    client, auth_headers, calendar, ha_mock
):
    client.portal.call(calendar.sync)
    identity = read(client, auth_headers)["events"][0]["id"]
    ha_mock.calendar_xml = report()
    client.portal.call(calendar.sync)
    assert read(client, auth_headers)["total"] == 0
    row = read(client, auth_headers, include_inactive=True)["events"][0]
    assert row["id"] == identity and row["status"] == "removed"


@pytest.mark.parametrize(
    "code,expected",
    [
        (401, "CALENDAR_AUTH_FAILED"),
        (302, "CALENDAR_REDIRECT_BLOCKED"),
        (500, "CALENDAR_UNAVAILABLE"),
        (405, "CALENDAR_UNSUPPORTED"),
    ],
)
def test_error_preserves_cache_marks_stale_and_does_not_follow_redirect(
    client, auth_headers, calendar, ha_mock, code, expected
):
    client.portal.call(calendar.sync)
    old = read(client, auth_headers)["events"]
    ha_mock.calendar_code = code
    response = client.post("/api/v1/calendar/sync", headers=auth_headers)
    assert response.status_code == 503 and response.json()["detail"]["code"] == expected
    data = read(client, auth_headers)
    assert data["stale"] and data["events"] == old and data["error_code"] == expected
    assert all(r.url.host in {"ha.test", "127.0.0.1"} for r in ha_mock.requests)


def test_partial_or_unsupported_snapshot_does_not_remove_previous_events(
    client, auth_headers, calendar, ha_mock
):
    client.portal.call(calendar.sync)
    old = read(client, auth_headers)["events"]
    for body in [
        report(ical(BASE + "\r\nRRULE:FREQ=DAILY")),
        report(ical(BASE), status="HTTP/1.1 404 Gone"),
        b"private-invalid-data",
    ]:
        ha_mock.calendar_xml = body
        with pytest.raises(CalendarError):
            client.portal.call(calendar.sync)
        assert read(client, auth_headers)["events"] == old and read(client, auth_headers)["stale"]


def test_query_uses_expand_bounded_window_and_report_has_no_cloud_links(
    client, auth_headers, calendar, ha_mock
):
    client.portal.call(calendar.sync)
    request = next(r for r in ha_mock.requests if r.method == "REPORT")
    tree = ET.fromstring(request.content)
    expand = tree.find(".//{urn:ietf:params:xml:ns:caldav}expand")
    assert expand.attrib == {"start": "20261010T000000Z", "end": "20261220T000000Z"}
    assert request.headers["Depth"] == "1" and "test-password" not in request.content.decode()
    assert "test-password" not in repr(settings)


def test_clock_staleness_and_scope_change_never_exposes_old_calendar(
    client, auth_headers, calendar, monkeypatch
):
    client.portal.call(calendar.sync)
    later = NOW + timedelta(hours=1)
    monkeypatch.setattr(clock, "utcnow", lambda: later)
    assert read(client, auth_headers)["stale"]
    monkeypatch.setattr(clock, "utcnow", lambda: NOW - timedelta(hours=1))
    assert read(client, auth_headers)["stale"]
    calendar.config_key = "different-synthetic-scope"
    assert read(client, auth_headers)["events"] == []


def test_sync_is_serial_and_storage_rollback_preserves_snapshot(
    client, auth_headers, calendar, ha_mock, monkeypatch
):
    client.portal.call(calendar.sync)
    old = read(client, auth_headers)["events"]
    from sqlalchemy import event

    def fail_update(connection, cursor, statement, parameters, context, many):
        if statement.startswith("UPDATE calendar_events "):
            raise SQLAlchemyError("private-db-error")

    ha_mock.calendar_xml = report(ical(BASE.replace("Встреча", "Новое имя")))
    event.listen(base.engine.sync_engine, "before_cursor_execute", fail_update)
    try:
        with pytest.raises(CalendarError):
            client.portal.call(calendar.sync)
    finally:
        event.remove(base.engine.sync_engine, "before_cursor_execute", fail_update)
    assert read(client, auth_headers)["events"] == old
    assert read(client, auth_headers)["error_code"] == "CALENDAR_STORAGE_ERROR"

    async def twice():
        await asyncio.gather(calendar.sync(), calendar.sync())

    client.portal.call(twice)
    assert read(client, auth_headers)["events"][0]["revision"] == 2


def test_network_wait_holds_no_db_transaction(client, auth_headers, calendar, ha_mock, monkeypatch):
    original = calendar.download

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        async def delayed(*args):
            started.set()
            await release.wait()
            return await original(*args)

        monkeypatch.setattr(calendar, "download", delayed)
        task = asyncio.create_task(calendar.sync())
        await asyncio.wait_for(started.wait(), 2)
        async with asyncio.timeout(2):
            async with base.async_session() as session, session.begin():
                await session.connection(execution_options={"sqlite_immediate": True})
                await session.execute(select(CalendarEvent))
        release.set()
        await task

    client.portal.call(scenario)


def test_local_url_and_credentials_validation():
    assert Settings(
        _env_file=None, calendar_url="http://127.0.0.1:8533/calendar/synthetic/"
    ).calendar_url
    for url in [
        "https://example.com/calendar/",
        "http://8.8.8.8/calendar/",
        "http://127.0.0.1/calendar/?secret=x",
        "http://user:private@127.0.0.1/calendar/",
        "http://127.0.0.1/calendar",
        "ftp://192.168.1.2/calendar/",
    ]:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, calendar_url=url)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, calendar_username="synthetic", calendar_password="")
