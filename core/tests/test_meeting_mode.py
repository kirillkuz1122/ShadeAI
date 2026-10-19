import asyncio
import json
from datetime import timedelta

import httpx
import pytest

from app.core import clock
from app.core.config import settings
from app.db import base
from app.db.models import MeetingLease
from app.services.meeting.service import MeetingService
from tests.test_calendar_codec import BASE, ical, report
from tests.test_calendar_service import NOW
from tests.test_calendar_service import calendar as calendar


@pytest.fixture
def mode(client, calendar, monkeypatch):
    monkeypatch.setattr(settings, "meeting_mode_enabled", True)
    monkeypatch.setattr(settings, "meeting_mode_allowed_switches", ["switch.test"])
    service = MeetingService(calendar, client.app.state.ha_client)
    client.app.state.meeting = service
    client.portal.call(calendar.sync)
    yield service
    client.portal.call(service.close)


def events(client, headers):
    return client.get("/api/v1/calendar/events", headers=headers).json()["events"]


def approve(client, headers, row, **changes):
    url = f"/api/v1/calendar/events/{row['id']}/meeting"
    detail = client.get(url, headers=headers).json()
    body = (
        dict(
            decision="approve",
            event_revision=row["revision"],
            policy_scope=detail["policy_scope"],
            targets=["switch.test"],
        )
        | changes
    )
    return client.post(url, headers=headers, json=body)


def move(client, calendar, monkeypatch, hour, minute=0, sync=True):
    stamp = NOW.replace(hour=hour, minute=minute)
    monkeypatch.setattr(clock, "utcnow", lambda: stamp)
    if sync:
        client.portal.call(calendar.sync)


def state(client, headers):
    response = client.get("/api/v1/calendar/meeting", headers=headers)
    assert response.status_code == 200
    return response.json()


def sent(ha_mock):
    return [r for r in ha_mock.requests if r.method == "POST" and "/services/switch/" in r.url.path]


def test_default_off_no_commands_and_protected(client, auth_headers, ha_mock):
    assert client.get("/api/v1/calendar/meeting").status_code == 401
    assert state(client, auth_headers)["policy"]["enabled"] is False
    client.portal.call(client.app.state.meeting.tick)
    assert not sent(ha_mock)


def test_explicit_scope_target_and_event_revision_required(client, auth_headers, mode, ha_mock):
    row = events(client, auth_headers)[0]
    assert approve(client, auth_headers, row, policy_scope="a" * 64).status_code == 409
    assert approve(client, auth_headers, row, targets=["switch.other"]).status_code == 422
    assert approve(client, auth_headers, row, event_revision=row["revision"] + 1).status_code == 409
    assert not sent(ha_mock)
    assert approve(client, auth_headers, row).status_code == 200
    assert state(client, auth_headers)["plans"][0]["status"] == "approved"
    assert not sent(ha_mock)


def test_start_restore_owned_state_and_no_duplicate(
    client, auth_headers, calendar, mode, monkeypatch, ha_mock
):
    row = events(client, auth_headers)[0]
    assert approve(client, auth_headers, row).status_code == 200
    move(client, calendar, monkeypatch, 5)
    client.portal.call(mode.tick)
    lease = state(client, auth_headers)["leases"][0]
    assert lease["state"] == "active" and lease["event_id"] is not None and len(sent(ha_mock)) == 1
    assert "private-mode-user" not in json.dumps(state(client, auth_headers))
    client.portal.call(mode.tick)
    assert len(sent(ha_mock)) == 1
    move(client, calendar, monkeypatch, 6)
    client.portal.call(mode.tick)
    lease = state(client, auth_headers)["leases"][0]
    assert lease["state"] == "completed" and lease["reason"] == "RESTORE_OBSERVED"
    assert [r.url.path.rsplit("/", 1)[-1] for r in sent(ha_mock)] == ["turn_on", "turn_off"]
    client.portal.call(mode.tick)
    assert len(sent(ha_mock)) == 2


def test_already_on_and_manual_context_change_are_not_overwritten(
    client, auth_headers, calendar, mode, monkeypatch, ha_mock
):
    ha_mock.switch_state["state"] = "on"
    row = events(client, auth_headers)[0]
    approve(client, auth_headers, row)
    move(client, calendar, monkeypatch, 5)
    client.portal.call(mode.tick)
    assert state(client, auth_headers)["leases"][0]["state"] == "external" and not sent(ha_mock)
    move(client, calendar, monkeypatch, 6)
    client.portal.call(mode.tick)
    assert not sent(ha_mock) and ha_mock.switch_state["state"] == "on"


def test_manual_context_change_preserved_even_when_state_stays_on(
    client, auth_headers, calendar, mode, monkeypatch, ha_mock
):
    approve(client, auth_headers, events(client, auth_headers)[0])
    move(client, calendar, monkeypatch, 5)
    client.portal.call(mode.tick)
    ha_mock.switch_state["context"] = {
        "id": "manual_different_context",
        "user_id": "private-person",
    }
    move(client, calendar, monkeypatch, 6)
    client.portal.call(mode.tick)
    assert state(client, auth_headers)["leases"][0]["reason"] == "MANUAL_CHANGE_PRESERVED"
    assert len(sent(ha_mock)) == 1 and ha_mock.switch_state["state"] == "on"


def test_overlapping_meetings_share_one_lease_until_last_end(
    client, auth_headers, calendar, mode, monkeypatch, ha_mock
):
    second = (
        BASE.replace("synthetic-one", "synthetic-two")
        .replace("T050000Z", "T053000Z")
        .replace("T060000Z", "T063000Z")
    )
    ha_mock.calendar_xml = report(ical(BASE, second))
    client.portal.call(calendar.sync)
    for row in events(client, auth_headers):
        assert approve(client, auth_headers, row).status_code == 200
    for hour, minute in [(5, 0), (5, 30), (6, 0)]:
        move(client, calendar, monkeypatch, hour, minute)
        client.portal.call(mode.tick)
        assert len(sent(ha_mock)) == 1 and ha_mock.switch_state["state"] == "on"
    move(client, calendar, monkeypatch, 6, 30)
    client.portal.call(mode.tick)
    assert len(sent(ha_mock)) == 2 and ha_mock.switch_state["state"] == "off"


def test_cancelled_event_restores_but_stale_cannot_start_new_mode(
    client, auth_headers, calendar, mode, monkeypatch, ha_mock
):
    approve(client, auth_headers, events(client, auth_headers)[0])
    move(client, calendar, monkeypatch, 5, sync=False)
    client.portal.call(mode.tick)
    assert not sent(ha_mock)
    client.portal.call(calendar.sync)
    client.portal.call(mode.tick)
    assert len(sent(ha_mock)) == 1
    ha_mock.calendar_xml = report()
    client.portal.call(calendar.sync)
    client.portal.call(mode.tick)
    assert len(sent(ha_mock)) == 2 and ha_mock.switch_state["state"] == "off"


def test_stale_calendar_does_not_prevent_stored_end_restoration(
    client, auth_headers, calendar, mode, monkeypatch, ha_mock
):
    approve(client, auth_headers, events(client, auth_headers)[0])
    move(client, calendar, monkeypatch, 5)
    client.portal.call(mode.tick)
    move(client, calendar, monkeypatch, 6, 1, sync=False)
    client.portal.call(mode.tick)
    assert (
        len(sent(ha_mock)) == 2 and state(client, auth_headers)["leases"][0]["state"] == "completed"
    )


def test_timeout_unknown_no_retry_and_ack_does_not_replay_same_event(
    client, auth_headers, calendar, mode, monkeypatch, ha_mock
):
    approve(client, auth_headers, events(client, auth_headers)[0])
    move(client, calendar, monkeypatch, 5)

    def timeout():
        raise httpx.ReadTimeout("synthetic")

    ha_mock.overrides["/api/services/switch/turn_on"] = timeout
    client.portal.call(mode.tick)
    lease = state(client, auth_headers)["leases"][0]
    assert lease["state"] == "unknown" and len(sent(ha_mock)) == 1
    client.portal.call(mode.tick)
    assert len(sent(ha_mock)) == 1
    path = "/api/v1/calendar/meeting/leases/switch.test/ack"
    for invalid in (False, 1, "true"):
        assert (
            client.post(
                path,
                headers=auth_headers,
                json=dict(generation=lease["generation"], checked=invalid),
            ).status_code
            == 422
        )
    assert (
        client.post(
            path, headers=auth_headers, json=dict(generation=lease["generation"], checked=True)
        ).status_code
        == 200
    )
    client.portal.call(mode.tick)
    assert len(sent(ha_mock)) == 1


def test_restart_inflight_becomes_unknown_without_replay(
    client, auth_headers, calendar, mode, monkeypatch, ha_mock
):
    approve(client, auth_headers, events(client, auth_headers)[0])
    move(client, calendar, monkeypatch, 5)
    # Заблокировать только фазу отправки: durable discovery остаётся настоящим.
    original = mode.transition

    async def no_transition(entity):
        pass

    monkeypatch.setattr(mode, "transition", no_transition)
    client.portal.call(mode.tick)

    async def mark():
        async with base.async_session() as session, session.begin():
            row = await session.get(MeetingLease, "switch.test")
            row.state = "applying"

    client.portal.call(mark)
    monkeypatch.setattr(mode, "transition", original)
    recovered = MeetingService(calendar, mode.client)
    recovered.enabled = False
    client.portal.call(recovered.start)
    recovered.enabled = True
    client.portal.call(recovered.tick)
    assert state(client, auth_headers)["leases"][0]["state"] == "unknown" and not sent(ha_mock)


def test_network_wait_releases_db_and_disable_can_complete_inflight(
    client, auth_headers, calendar, mode, monkeypatch, ha_mock
):
    row = events(client, auth_headers)[0]
    approve(client, auth_headers, row)
    move(client, calendar, monkeypatch, 5)
    original = mode.client.call_service

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        async def delayed(*args):
            started.set()
            await release.wait()
            return await original(*args)

        monkeypatch.setattr(mode.client, "call_service", delayed)
        job = asyncio.create_task(mode.tick())
        await asyncio.wait_for(started.wait(), 2)
        async with asyncio.timeout(2):
            await mode.decide(row["id"], "disable", 1, None, [])
        release.set()
        await job

    client.portal.call(scenario)
    client.portal.call(mode.tick)
    assert (
        len(sent(ha_mock)) == 2
        and state(client, auth_headers)["leases"][0]["reason"] == "RESTORE_OBSERVED"
    )


def test_no_context_never_sends_and_policy_removal_never_restores_unallowed_target(
    client, auth_headers, calendar, mode, monkeypatch, ha_mock
):
    approve(client, auth_headers, events(client, auth_headers)[0])
    move(client, calendar, monkeypatch, 5)
    ha_mock.switch_state.pop("context")
    client.portal.call(mode.tick)
    assert (
        not sent(ha_mock)
        and state(client, auth_headers)["leases"][0]["reason"] == "CONTEXT_REQUIRED"
    )
    ha_mock.switch_state["context"] = {"id": "available_after_read_retry"}
    stamp = clock.utcnow() + timedelta(seconds=31)
    monkeypatch.setattr(clock, "utcnow", lambda: stamp)
    client.portal.call(mode.tick)
    assert len(sent(ha_mock)) == 1
    mode.allowed = ()
    move(client, calendar, monkeypatch, 6)
    client.portal.call(mode.tick)
    assert (
        len(sent(ha_mock)) == 1
        and state(client, auth_headers)["leases"][0]["reason"] == "POLICY_REVOKED"
    )
