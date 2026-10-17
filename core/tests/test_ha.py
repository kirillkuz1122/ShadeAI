import asyncio
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import clock
from app.core.config import settings
from app.core.logging import local_logging
from app.db import base
from app.db.models import EventLog
from app.services.ha_bridge.audit import maintain_events
from app.services.ha_bridge.client import HAClient, HAError
from app.services.notification.maintenance import cleanup


def command(client, headers, **changes):
    return client.post(
        "/api/v1/devices/light.test/command",
        headers=headers,
        json={"action": "turn_on", "params": {"brightness": 128}} | changes,
    )


def journal(client, headers, query=""):
    response = client.get("/api/v1/events" + query, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_devices_live_state_filter_and_shared_client(client, auth_headers, ha_mock):
    ha_mock.states.append(ha_mock.state | {"entity_id": "sensor.temperature", "state": "22"})
    data = client.get("/api/v1/devices", headers=auth_headers).json()
    assert len(data["devices"]) == 2
    assert data["devices"][0]["name"] == "Тестовый свет"
    filtered = client.get("/api/v1/devices?domain=sensor", headers=auth_headers).json()
    assert [item["entity_id"] for item in filtered["devices"]] == ["sensor.temperature"]
    state = client.get("/api/v1/devices/light.test/state", headers=auth_headers).json()
    assert state["state"] == "on" and state["last_updated"].endswith("Z")
    assert len(ha_mock.clients) == 1
    client.get("/api/v1/health")
    assert len(ha_mock.clients) == 1
    assert not ha_mock.clients[0].is_closed


@pytest.mark.parametrize("path", ["/devices", "/devices/light.test/state", "/events"])
def test_ha_reads_require_auth(client, ha_mock, path):
    assert client.get("/api/v1" + path).status_code == 401
    assert not ha_mock.requests


def test_command_writes_intention_before_network_without_db_lock(client, auth_headers, ha_mock):
    observed = []

    def inspect(request):
        if request.method == "POST":
            path = make_url(settings.db_url).database
            with closing(sqlite3.connect(path, timeout=0.1)) as db:
                row = db.execute("SELECT event_type,payload_json FROM events_log").fetchone()
                observed.append(row)
                db.execute("BEGIN IMMEDIATE")
                db.rollback()

    ha_mock.hook = inspect
    result = command(client, auth_headers)
    assert result.status_code == 200
    assert observed[0][0] == "command_requested"
    assert json.loads(observed[0][1])["status"] == "pending"
    assert result.json()["new_state"] == "on"
    assert result.json()["state_observed"] is True
    assert "result" not in result.json()
    events = journal(client, auth_headers)
    assert events["total"] == 1
    assert events["events"][0]["id"] == result.json()["event_id"]
    assert events["events"][0]["type"] == "command_executed"
    assert events["events"][0]["payload"]["outcome"] == "accepted"


@pytest.mark.parametrize(
    "failure,status,code,outcome",
    [
        (401, 503, "HA_AUTH_FAILED", "rejected"),
        (403, 503, "HA_AUTH_FAILED", "rejected"),
        (400, 400, "HA_COMMAND_REJECTED", "rejected"),
        (404, 400, "HA_COMMAND_REJECTED", "rejected"),
        (500, 502, "HA_SERVER_ERROR", "unknown"),
        (302, 502, "HA_BAD_RESPONSE", "unknown"),
        ("connect", 503, "HA_UNAVAILABLE", "not_sent"),
        ("read_timeout", 504, "HA_TIMEOUT", "unknown"),
        ("connect_timeout", 504, "HA_TIMEOUT", "not_sent"),
    ],
)
def test_command_failures_are_audited_without_retry(
    client, auth_headers, ha_mock, failure, status, code, outcome
):
    if isinstance(failure, int):
        ha_mock.status_code = failure
    else:
        error = {
            "connect": httpx.ConnectError,
            "read_timeout": httpx.ReadTimeout,
            "connect_timeout": httpx.ConnectTimeout,
        }[failure]
        ha_mock.error = error("private-upstream-secret")
    response = command(client, auth_headers)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert response.json()["detail"]["outcome"] == outcome
    assert len(ha_mock.requests) == 1
    event = journal(client, auth_headers)["events"][0]
    assert event["type"] == "command_failed"
    assert event["payload"]["error_code"] == code
    assert event["payload"]["outcome"] == outcome
    assert "private-upstream-secret" not in response.text + json.dumps(event)


def test_readback_failure_does_not_repeat_or_reject_accepted_command(client, auth_headers, ha_mock):
    ha_mock.overrides["/api/states/light.test"] = lambda: httpx.Response(404)
    response = command(client, auth_headers)
    assert response.status_code == 200
    assert response.json()["new_state"] is None
    assert response.json()["state_observed"] is False
    assert sum(r.method == "POST" for r in ha_mock.requests) == 1
    assert journal(client, auth_headers)["events"][0]["type"] == "command_executed"


@pytest.mark.parametrize("body", [{}, {"state": "on"}, [3], {"entity_id": "switch.other"}])
def test_invalid_upstream_state(client, auth_headers, ha_mock, body):
    ha_mock.overrides["/api/states/light.test"] = lambda: httpx.Response(200, json=body)
    response = client.get("/api/v1/devices/light.test/state", headers=auth_headers)
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "HA_BAD_RESPONSE"


@pytest.mark.parametrize(
    "response_factory",
    [
        lambda: httpx.Response(200, content=b"private-invalid-json"),
        lambda: httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1)),
        lambda: httpx.Response(200, json={"not": "a list"}),
    ],
)
def test_invalid_ha_service_response_is_unknown(client, auth_headers, ha_mock, response_factory):
    ha_mock.overrides["/api/services/light/turn_on"] = response_factory
    response = command(client, auth_headers)
    assert response.status_code == 502
    assert response.json()["detail"]["outcome"] == "unknown"
    assert "private-invalid-json" not in response.text


@pytest.mark.parametrize(
    "body",
    [
        {"action": "../turn_on"},
        {"params": {"entity_id": "light.other"}},
        {"params": {"target": {"area_id": "all"}}},
        {"params": {"x": "x" * 8193}},
        {"action": "turn_on", "unknown": "secret"},
    ],
)
def test_invalid_command_never_reaches_ha_or_journal(client, auth_headers, ha_mock, body):
    assert command(client, auth_headers, **body).status_code == 422
    assert not ha_mock.requests
    assert journal(client, auth_headers)["total"] == 0


def test_legacy_domain_mismatch_and_oversized_command(client, auth_headers, ha_mock):
    response = client.post(
        "/api/v1/ha/action",
        headers=auth_headers,
        json={"entity_id": "light.test", "domain": "switch", "service": "turn_on"},
    )
    assert response.status_code == 422
    assert (
        client.post(
            "/api/v1/devices/light.test/command", headers=auth_headers, content=b"x" * 65537
        ).status_code
        == 413
    )
    assert not ha_mock.requests


def test_audit_and_local_logs_do_not_store_params_tokens_or_responses(
    client, auth_headers, ha_mock
):
    ha_mock.result = [ha_mock.state | {"attributes": {"private": "upstream-secret-749183"}}]
    result = command(client, auth_headers, params={"pin": "839174", "message": "private-message"})
    assert result.status_code == 200
    events = journal(client, auth_headers)

    async def raw_rows():
        async with base.async_session() as session:
            return "".join(await session.scalars(select(EventLog.payload_json)))

    contents = client.portal.call(raw_rows) + json.dumps(events)
    contents += "".join(path.read_text() for path in Path(settings.log_dir).glob("shade.log*"))
    for secret in [
        "839174",
        "private-message",
        "upstream-secret-749183",
        settings.ha_token,
        settings.api_key,
    ]:
        assert secret not in contents


def test_events_filters_total_and_retention(client, auth_headers, monkeypatch):
    now = datetime(2026, 10, 17, 12, tzinfo=UTC)
    monkeypatch.setattr(clock, "utcnow", lambda: now)
    for _ in range(3):
        assert command(client, auth_headers).status_code == 200
    page = journal(client, auth_headers, "?limit=1&offset=1&from=2026-10-17&to=2026-10-17")
    assert page["total"] == 3 and len(page["events"]) == 1
    assert journal(client, auth_headers, "?type=command_failed")["total"] == 0
    assert journal(client, auth_headers, "?offset=99")["total"] == 3
    previous_id = journal(client, auth_headers)["events"][0]["id"]
    monkeypatch.setattr(clock, "utcnow", lambda: now + timedelta(days=91))
    assert journal(client, auth_headers)["total"] == 0
    client.portal.call(cleanup)
    fresh = command(client, auth_headers)
    assert fresh.json()["event_id"] > previous_id


@pytest.mark.parametrize(
    "query",
    [
        "limit=501",
        "offset=-1",
        "from=bad",
        "to=2026-02-30",
        "from=2026-10-17T12:00:00%2B00:99",
        "from=2026-10-18&to=2026-10-17",
        "type=unknown",
    ],
)
def test_event_query_validation(client, auth_headers, query):
    assert client.get("/api/v1/events?" + query, headers=auth_headers).status_code == 422


@pytest.mark.parametrize("at", [1, 2])
def test_audit_failure_prevents_send_or_preserves_pending(
    client, auth_headers, ha_mock, monkeypatch, at
):
    class FailingSession(AsyncSession):
        commits = 0

        async def commit(self):
            self.commits += 1
            if self.commits == at:
                raise OperationalError("test", {}, Exception("private-db-secret"))
            await super().commit()

    factory = async_sessionmaker(base.engine, class_=FailingSession, expire_on_commit=False)
    with monkeypatch.context() as patch:
        patch.setattr(base, "async_session", factory)
        response = command(client, auth_headers)
    assert response.status_code == 503
    assert "private-db-secret" not in response.text
    if at == 1:
        assert not ha_mock.requests
        assert journal(client, auth_headers)["total"] == 0
    else:
        assert len(ha_mock.requests) == 1
        assert response.json()["detail"]["outcome"] == "accepted"
        assert journal(client, auth_headers)["events"][0]["type"] == "command_requested"

        async def recover():
            async with base.async_session() as session:
                await maintain_events(session, recover=True)

        client.portal.call(recover)
        event = journal(client, auth_headers)["events"][0]
        assert event["type"] == "command_interrupted"
        assert event["payload"]["outcome"] == "unknown"
        assert len(ha_mock.requests) == 1


def test_health_db_failure_and_ha_degradation(client, ha_mock, monkeypatch):
    ha_mock.status_code = 401
    response = client.get("/api/v1/health")
    assert response.status_code == 200 and response.json()["status"] == "degraded"
    assert response.json()["ha_status"] == "HA_AUTH_FAILED"
    assert response.json()["db_connected"] is True
    assert response.json()["services"]["analytics"] == "not_implemented"
    original = AsyncSession.execute

    async def fail_probe(self, statement, *args, **kwargs):
        if str(statement) == "SELECT 1":
            raise OperationalError("probe", {}, Exception("private-secret"))
        return await original(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", fail_probe)
    response = client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json()["status"] == "error"
    assert "private-secret" not in response.text


def test_ha_outage_does_not_break_notification_ingestion(client, ha_mock, auth_headers):
    ha_mock.available = False
    assert client.get("/api/v1/health").json()["status"] == "degraded"
    response = client.post(
        "/api/v1/notifications",
        headers=auth_headers,
        json={
            "app_name": "ru.ozon.app.android",
            "title": "Доставка",
            "text": "Курьер вечером",
            "timestamp": clock.iso_utc(clock.utcnow()),
        },
    )
    assert response.status_code == 201


def test_log_rotation_is_bounded_and_private(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "log_dir", str(tmp_path / "rotation"))
    monkeypatch.setattr(settings, "log_max_bytes", 1024)
    monkeypatch.setattr(settings, "log_backup_count", 2)
    with local_logging() as logger:
        for number in range(150):
            logger.info("command event_id=%s status=success code=none", number)
    files = list((tmp_path / "rotation").glob("shade.log*"))
    assert len(files) == 3
    assert all(
        path.stat().st_size <= 1024 and path.stat().st_mode & 0o777 == 0o600 for path in files
    )


def test_empty_token_and_total_timeout_without_network(monkeypatch):
    async def scenario():
        monkeypatch.setattr(settings, "ha_token", "")
        client = HAClient()
        try:
            with pytest.raises(HAError, match="HA_NOT_CONFIGURED"):
                await client.ping()
        finally:
            await client.close()
        monkeypatch.setattr(settings, "ha_token", "synthetic-token")
        monkeypatch.setattr(settings, "ha_timeout_seconds", 0.1)
        client = HAClient()
        await client._client.aclose()
        started = []

        async def slow(request):
            started.append(True)
            await asyncio.sleep(1)
            raise AssertionError("Общий таймаут не сработал")

        client._client = httpx.AsyncClient(
            base_url="http://ha.test", transport=httpx.MockTransport(slow)
        )
        try:
            with pytest.raises(HAError, match="HA_TIMEOUT"):
                await client.ping()
            assert len(started) == 1
        finally:
            await client.close()

    asyncio.run(scenario())
