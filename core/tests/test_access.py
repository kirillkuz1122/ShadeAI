import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.core import clock
from app.core.config import Settings, settings
from app.db import base
from app.db.models import AccessGate, AccessGrant, EventLog, NotificationRaw
from app.services.access.service import AccessError, AccessService
from app.services.notification.extraction import (
    ExtractedEntities,
    ExtractedNotification,
    ExtractedTime,
)

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
KEYPAD = "synthetic-shade-keypad-token-00001"
KEY_HEADERS = {"Authorization": "Bearer " + KEYPAD}


@pytest.fixture
def enabled(client, monkeypatch):
    monkeypatch.setattr(clock, "utcnow", lambda: NOW)
    monkeypatch.setattr(settings, "access_enabled", True)
    monkeypatch.setattr(settings, "access_allowed_locks", ["lock.test"])
    monkeypatch.setattr(settings, "access_keypad_token", KEYPAD)
    return client.app.state.access


def delivery(client, auth_headers, text="Синтетическая посылка доставляется", event_id=None):
    body = dict(
        app_name="ru.ozon.app.android",
        title="Доставка",
        text=text,
        timestamp=NOW.isoformat(),
        priority="default",
        event_id=event_id or str(uuid4()),
    )
    response = client.post("/api/v1/notifications", headers=auth_headers, json=body)
    assert response.status_code == 201
    identity = response.json()["id"]
    extracted = ExtractedNotification(
        category="delivery",
        priority="default",
        intent="delivery_event",
        entities=ExtractedEntities(subject="Посылка", location=None, service=None),
        time=ExtractedTime(source=None, timezone="UTC", at=None, date=None, resolution="absent"),
    )

    async def finish():
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            await session.execute(
                update(NotificationRaw)
                .where(NotificationRaw.id == identity)
                .values(
                    processing_status="processed",
                    is_processed=1,
                    category="delivery",
                    extracted_data_json=extracted.model_dump_json(),
                )
            )

    client.portal.call(finish)
    return identity, body


def issue(client, headers, notification_id, **changes):
    scope = client.get("/api/v1/access", headers=headers).json()["policy_scope"]
    return client.post(
        "/api/v1/access/grants",
        headers=headers,
        json=dict(
            notification_id=notification_id,
            entity_id="lock.test",
            duration_minutes=2,
            policy_scope=scope,
            confirmed=True,
            delivery_checked=True,
        )
        | changes,
    )


def verify(client, pin, headers=KEY_HEADERS, entity="lock.test"):
    return client.post(
        "/api/v1/access/keypad/verify", headers=headers, json={"pin": pin, "entity_id": entity}
    )


def revoke(client, headers, grant, **body):
    return client.post(f"/api/v1/access/grants/{grant['id']}/revoke", headers=headers, json=body)


def commands(mock):
    return [r for r in mock.requests if r.url.path == "/api/services/lock/unlock"]


def test_default_disabled_and_separate_key_permissions(client, auth_headers, monkeypatch):
    assert client.get("/api/v1/access").status_code == 401
    assert client.get("/api/v1/access", headers=auth_headers).json()["enabled"] is False
    assert client.post("/api/v1/access/grants").status_code == 401
    assert verify(client, "123456").status_code == 401
    monkeypatch.setattr(settings, "access_keypad_token", KEYPAD)
    assert client.get("/api/v1/access", headers=KEY_HEADERS).status_code == 401
    assert verify(client, "123456", auth_headers).status_code == 401
    assert verify(client, "123456").status_code == 503
    assert verify(client, "123456", {"Authorization": b"Bearer \xff"}).status_code == 401


@pytest.mark.parametrize(
    "values",
    [
        {"access_enabled": True},
        {"access_enabled": True, "access_allowed_locks": ["lock.test"]},
        {"access_allowed_locks": ["light.test"]},
        {"access_keypad_token": "short"},
        {"access_keypad_token": "x" * 32, "api_key": "x" * 32},
    ],
)
def test_configuration_rejects_missing_targets_or_shared_secret(values):
    args = dict(
        _env_file=None,
        SHADE_API_KEY="x" * 32,
        access_enabled=False,
        access_allowed_locks=[],
        access_keypad_token="",
    )
    # Конструктор принимает имена полей (кроме validation_alias SHADE_API_KEY).
    args.update(values)
    if "api_key" in args:
        args["SHADE_API_KEY"] = args.pop("api_key")
    with pytest.raises(ValidationError):
        Settings(**args)


def test_one_time_pin_owner_only_dedupe_and_audited_unlock(client, auth_headers, enabled, ha_mock):
    source, body = delivery(client, auth_headers)
    response = issue(client, auth_headers, source)
    assert response.status_code == 200
    grant = response.json()
    pin = grant["pin"]
    assert len(pin) == 6 and pin.isdecimal() and grant["state"] == "active"
    assert response.headers["cache-control"] == "no-store" and not commands(ha_mock)
    duplicate = client.post("/api/v1/notifications", headers=auth_headers, json=body)
    assert duplicate.json()["id"] == source
    assert issue(client, auth_headers, source).json()["pin"] is None
    assert issue(client, auth_headers, source, duration_minutes=3).status_code == 409
    page = client.get("/api/v1/access", headers=auth_headers).json()
    assert page["grants"][0]["pin"] is None
    assert "pin_digest" not in str(page) and KEYPAD not in str(page)
    assert (
        client.get(f"/api/v1/access/grants/{grant['id']}", headers=auth_headers).json()["pin"]
        is None
    )
    accepted = verify(client, pin)
    assert accepted.status_code == 200 and accepted.json() == dict(
        state="used", error_code=None, new_state="unlocked", state_observed=True
    )
    assert verify(client, pin).status_code == 403 and len(commands(ha_mock)) == 1
    assert issue(client, auth_headers, source).json()["state"] == "used"
    assert issue(client, auth_headers, source).json()["pin"] is None

    async def privacy():
        async with base.async_session() as session:
            row = await session.get(AccessGrant, grant["id"])
            assert not row.pin_digest
            events = list(await session.scalars(select(EventLog.payload_json)))
            assert pin not in str(events) and "Синтетическая" not in str(events)
            assert len(events) == 1 and '"service": "unlock"' in events[0]

    client.portal.call(privacy)


@pytest.mark.parametrize(
    "changes",
    [
        dict(confirmed=False),
        dict(delivery_checked=False),
        dict(confirmed="true"),
        dict(duration_minutes=16),
        dict(duration_minutes=True),
        dict(entity_id="light.test"),
    ],
)
def test_explicit_consent_and_window_validation(client, auth_headers, enabled, changes, ha_mock):
    source, _ = delivery(client, auth_headers)
    response = issue(client, auth_headers, source, **changes)
    assert response.status_code == 422 and not commands(ha_mock)


@pytest.mark.parametrize(
    "mutation",
    [
        "pending",
        "invalid_llm",
        "changed_hash",
        "private_app",
        "deleted",
        "old",
        "future",
        "different_category",
    ],
)
def test_only_fresh_canonical_delivery_can_receive_access(
    client, auth_headers, enabled, mutation, ha_mock
):
    source, _ = delivery(client, auth_headers)

    async def change():
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            row = await session.get(NotificationRaw, source)
            if mutation == "deleted":
                await session.delete(row)
            elif mutation == "pending":
                row.processing_status = "pending"
            elif mutation == "invalid_llm":
                row.extracted_data_json = "{}"
            elif mutation == "changed_hash":
                row.text += " изменено"
            elif mutation == "private_app":
                row.app_name = "org.telegram.messenger"
            elif mutation == "different_category":
                row.category = "noise"
            else:
                row.created_at = (NOW + timedelta(days=2 if mutation == "future" else -2)).replace(
                    tzinfo=None
                )

    client.portal.call(change)
    assert issue(client, auth_headers, source).status_code == 409 and not commands(ha_mock)


@pytest.mark.parametrize("reason", ["expired", "revoked", "policy", "source_removed", "clock_back"])
def test_revocation_expiry_and_context_fail_closed(
    client, auth_headers, enabled, monkeypatch, ha_mock, reason
):
    source, _ = delivery(client, auth_headers)
    grant = issue(client, auth_headers, source).json()
    if reason == "expired":
        monkeypatch.setattr(clock, "utcnow", lambda: NOW + timedelta(minutes=2))
    elif reason == "clock_back":
        monkeypatch.setattr(clock, "utcnow", lambda: NOW - timedelta(seconds=1))
    elif reason == "revoked":
        assert revoke(client, auth_headers, grant).json()["state"] == "revoked"
    elif reason == "policy":
        monkeypatch.setattr(settings, "access_keypad_token", KEYPAD + "changed")
    else:

        async def remove():
            async with base.async_session() as session, session.begin():
                await session.connection(execution_options={"sqlite_immediate": True})
                await session.execute(delete(NotificationRaw).where(NotificationRaw.id == source))

        client.portal.call(remove)
    response = verify(
        client, grant["pin"], {"Authorization": "Bearer " + settings.access_keypad_token}
    )
    assert response.status_code == 403 and not commands(ha_mock)
    state = client.get(f"/api/v1/access/grants/{grant['id']}", headers=auth_headers).json()["state"]
    assert state in {"expired", "revoked"}
    monkeypatch.setattr(clock, "utcnow", lambda: NOW)
    assert verify(
        client, grant["pin"], {"Authorization": "Bearer " + settings.access_keypad_token}
    ).status_code in {403, 429}


def test_rate_limit_is_durable_and_five_bad_guesses_revoke(
    client, auth_headers, enabled, monkeypatch, ha_mock
):
    source, _ = delivery(client, auth_headers)
    grant = issue(client, auth_headers, source).json()
    bad = "000000" if grant["pin"] != "000000" else "000001"
    for _ in range(5):
        assert verify(client, bad).status_code == 403
    assert verify(client, grant["pin"]).status_code == 429

    async def inspect():
        async with base.async_session() as session:
            gate = await session.get(AccessGate, "lock.test")
            row = await session.get(AccessGrant, grant["id"])
            assert gate.attempts == 5 and row.bad_attempts == 5 and row.state == "revoked"

    client.portal.call(inspect)
    monkeypatch.setattr(clock, "utcnow", lambda: NOW + timedelta(seconds=61))
    assert verify(client, grant["pin"]).status_code == 403 and not commands(ha_mock)


def test_identical_payload_with_new_event_id_and_lock_collision(
    client, auth_headers, enabled, ha_mock
):
    source, _ = delivery(client, auth_headers)
    first = issue(client, auth_headers, source).json()
    same, _ = delivery(client, auth_headers)
    assert same != source and issue(client, auth_headers, same).json()["id"] == first["id"]
    different, _ = delivery(client, auth_headers, text="Другая синтетическая посылка")
    assert issue(client, auth_headers, different).status_code == 409
    assert not commands(ha_mock)


def test_timeout_unknown_consumed_without_retry_and_manual_ack(
    client, auth_headers, enabled, ha_mock
):
    source, _ = delivery(client, auth_headers)
    grant = issue(client, auth_headers, source).json()
    ha_mock.error = httpx.ReadTimeout("synthetic")
    result = verify(client, grant["pin"])
    assert result.status_code == 200 and result.json()["state"] == "unknown"
    ha_mock.error = None
    assert verify(client, grant["pin"]).status_code == 403 and len(commands(ha_mock)) == 1
    other, _ = delivery(client, auth_headers, text="Другая посылка")
    assert issue(client, auth_headers, other).status_code == 409
    assert revoke(client, auth_headers, grant).status_code == 409
    assert revoke(client, auth_headers, grant, checked="true").status_code == 422
    assert revoke(client, auth_headers, grant, checked=True).json()["state"] == "revoked"
    assert issue(client, auth_headers, other).json()["state"] == "active"
    assert len(commands(ha_mock)) == 1


def test_restart_revokes_active_and_never_replays_dispatch(client, auth_headers, enabled, ha_mock):
    source, _ = delivery(client, auth_headers)
    grant = issue(client, auth_headers, source).json()
    client.portal.call(enabled.start)
    assert verify(client, grant["pin"]).status_code == 403
    assert issue(client, auth_headers, source).json()["state"] == "revoked"

    async def interrupted():
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            row = await session.get(AccessGrant, grant["id"])
            row.state = "dispatching"
        service = AccessService(enabled.client)
        await service.start()

    client.portal.call(interrupted)
    state = client.get(f"/api/v1/access/grants/{grant['id']}", headers=auth_headers).json()
    assert state["state"] == "unknown" and not commands(ha_mock)


def test_concurrent_verification_and_revocation_never_repeat(
    client, auth_headers, enabled, monkeypatch
):
    source, _ = delivery(client, auth_headers)
    grant = issue(client, auth_headers, source).json()

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def fake(*args):
            calls.append(args)
            started.set()
            await release.wait()
            return dict(event_id=1, new_state="unlocked", state_observed=True)

        monkeypatch.setattr("app.services.access.service.execute_command", fake)
        first = asyncio.create_task(enabled.verify("lock.test", grant["pin"]))
        await started.wait()
        with pytest.raises(AccessError, match="ACCESS_BUSY"):
            await enabled.verify("lock.test", grant["pin"])
        with pytest.raises(AccessError, match="ACCESS_IN_FLIGHT"):
            await enabled.revoke(grant["id"])
        release.set()
        assert (await first)["state"] == "used" and len(calls) == 1

    client.portal.call(scenario)


def test_result_storage_failure_is_not_retried(client, auth_headers, enabled, monkeypatch, ha_mock):
    source, _ = delivery(client, auth_headers)
    grant = issue(client, auth_headers, source).json()
    original = base.async_session

    async def fake(*args):
        # Имитация отказа хранилища после уже принятой команды.
        def broken(*args, **kwargs):
            raise SQLAlchemyError("private-storage-data")

        monkeypatch.setattr(base, "async_session", broken)
        return dict(event_id=7, new_state="unlocked", state_observed=True)

    monkeypatch.setattr("app.services.access.service.execute_command", fake)
    result = verify(client, grant["pin"])
    monkeypatch.setattr(base, "async_session", original)
    assert result.status_code == 503 and "private-storage-data" not in result.text
    assert verify(client, grant["pin"]).status_code == 403
    assert revoke(client, auth_headers, grant).status_code == 409
    assert not commands(ha_mock)


def test_invalid_pin_and_body_never_echo_private_input(client, auth_headers, enabled):
    result = verify(client, "private-pin-data")
    assert result.status_code == 422 and "private-pin-data" not in result.text
    huge = client.post("/api/v1/access/keypad/verify", headers=KEY_HEADERS, content=b"x" * 65537)
    assert huge.status_code == 413


def test_monotonic_deadline_and_pin_history_prevent_revival_and_reuse(
    client, auth_headers, enabled, monkeypatch, ha_mock
):
    monkeypatch.setattr("app.services.access.service.secrets.randbelow", lambda _: 123456)
    source, _ = delivery(client, auth_headers)
    grant = issue(client, auth_headers, source).json()
    # Не менять глобальный time.monotonic event loop, только deadline сервиса.
    enabled.deadlines[grant["id"]] = 0
    assert verify(client, grant["pin"]).status_code == 403
    second, _ = delivery(client, auth_headers, text="Новая посылка")
    assert issue(client, auth_headers, second).status_code == 503
    assert not commands(ha_mock)


def test_pre_dispatch_audit_failure_sends_nothing_and_consumes_pin(
    client, auth_headers, enabled, monkeypatch, ha_mock
):
    from fastapi import HTTPException

    source, _ = delivery(client, auth_headers)
    grant = issue(client, auth_headers, source).json()

    async def not_sent(*args):
        raise HTTPException(503, {"outcome": "not_sent"})

    monkeypatch.setattr("app.services.access.service.execute_command", not_sent)
    result = verify(client, grant["pin"])
    assert result.json()["state"] == "failed" and result.json()["error_code"] == "ACCESS_NOT_SENT"
    assert verify(client, grant["pin"]).status_code == 403 and not commands(ha_mock)
