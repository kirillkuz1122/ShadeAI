from datetime import timedelta

from app.core import clock
from app.core.config import settings
from tests.test_calendar_codec import BASE, ical, report
from tests.test_calendar_service import NOW
from tests.test_calendar_service import calendar as calendar


def get(client, headers):
    response = client.get("/api/v1/calendar/reminders", headers=headers)
    assert response.status_code == 200
    return response.json()


def setup(client, calendar, monkeypatch):
    monkeypatch.setattr(settings, "calendar_reminders_enabled", True)
    client.portal.call(calendar.sync)


def test_reminders_default_disabled_and_protected(client, auth_headers):
    assert client.get("/api/v1/calendar/reminders").status_code == 401
    assert get(client, auth_headers)["enabled"] is False
    assert get(client, auth_headers)["reminders"] == []


def test_stable_schedule_generic_payload_and_source_revalidation(
    client, auth_headers, calendar, monkeypatch, ha_mock
):
    setup(client, calendar, monkeypatch)
    first = get(client, auth_headers)
    assert len(first["source_id"]) == 64
    row = first["reminders"][0]
    assert (
        first["version"] == 1
        and not first["stale"]
        and row["due_at"].startswith("2026-10-19T04:50:")
    )
    assert not row["due"] and row["expires_at"].startswith("2026-10-19T04:55:")
    assert len(row["id"]) == 36 and not {"title", "summary", "location", "text", "uid"} & row.keys()
    assert get(client, auth_headers)["reminders"][0]["id"] == row["id"]
    path = f"/api/v1/calendar/reminders/{row['id']}"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=auth_headers).json()["reminder"]["due"] is False
    ha_mock.calendar_xml = report(ical("UID:synthetic-one\r\nSTATUS:CANCELLED"))
    client.portal.call(calendar.sync)
    assert get(client, auth_headers)["reminders"] == []
    assert client.get(path, headers=auth_headers).status_code == 404


def test_event_change_and_lead_change_invalidate_old_id(
    client, auth_headers, calendar, monkeypatch, ha_mock
):
    setup(client, calendar, monkeypatch)
    old = get(client, auth_headers)["reminders"][0]
    ha_mock.calendar_xml = report(ical(BASE.replace("Встреча", "Другое имя")))
    client.portal.call(calendar.sync)
    revised = get(client, auth_headers)["reminders"][0]
    assert revised["id"] != old["id"] and revised["event_revision"] == 2
    monkeypatch.setattr(settings, "calendar_reminder_lead_minutes", 20)
    assert get(client, auth_headers)["reminders"][0]["id"] != revised["id"]
    assert (
        client.get(f"/api/v1/calendar/reminders/{revised['id']}", headers=auth_headers).status_code
        == 404
    )


def test_due_and_expiry_window_never_replays_old_reminder(
    client, auth_headers, calendar, monkeypatch
):
    setup(client, calendar, monkeypatch)
    identity = get(client, auth_headers)["reminders"][0]["id"]
    due = NOW.replace(hour=4, minute=50)
    monkeypatch.setattr(clock, "utcnow", lambda: due)
    client.portal.call(calendar.sync)
    assert get(client, auth_headers)["reminders"][0]["due"]
    late = due + timedelta(minutes=6)
    monkeypatch.setattr(clock, "utcnow", lambda: late)
    client.portal.call(calendar.sync)
    assert get(client, auth_headers)["reminders"] == []
    assert (
        client.get(f"/api/v1/calendar/reminders/{identity}", headers=auth_headers).status_code
        == 404
    )


def test_stale_source_blocks_validation_and_disable_cancels(
    client, auth_headers, calendar, monkeypatch, ha_mock
):
    setup(client, calendar, monkeypatch)
    identity = get(client, auth_headers)["reminders"][0]["id"]
    ha_mock.calendar_code = 500
    assert client.post("/api/v1/calendar/sync", headers=auth_headers).status_code == 503
    assert get(client, auth_headers)["stale"] and not get(client, auth_headers)["reminders"]
    assert (
        client.get(f"/api/v1/calendar/reminders/{identity}", headers=auth_headers).status_code
        == 503
    )
    monkeypatch.setattr(settings, "calendar_reminders_enabled", False)
    assert (
        client.get(f"/api/v1/calendar/reminders/{identity}", headers=auth_headers).status_code
        == 404
    )


def test_date_only_transparent_tentative_and_removed_are_not_scheduled(
    client, auth_headers, calendar, monkeypatch, ha_mock
):
    setup(client, calendar, monkeypatch)
    for body in [
        ical("UID:day\r\nDTSTART;VALUE=DATE:20261019"),
        ical(BASE + "\r\nTRANSP:TRANSPARENT"),
        ical(BASE + "\r\nSTATUS:TENTATIVE"),
    ]:
        ha_mock.calendar_xml = report(body)
        client.portal.call(calendar.sync)
        assert not get(client, auth_headers)["reminders"]


def test_overflow_is_explicit_not_silent_partial_schedule(
    client, auth_headers, calendar, monkeypatch, ha_mock
):
    setup(client, calendar, monkeypatch)
    ha_mock.calendar_xml = report(
        ical(*[BASE.replace("synthetic-one", f"synthetic-{i}") for i in range(51)])
    )
    client.portal.call(calendar.sync)
    data = get(client, auth_headers)
    assert data["overflow"] and data["reminders"] == []
