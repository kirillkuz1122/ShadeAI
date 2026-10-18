import asyncio
import copy
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core import clock
from app.core.config import Settings, settings
from app.db import base
from app.db.models import DeviceState, SensorHistory, TelemetryCheckpoint, TelemetryGap
from app.services.ha_bridge.client import HAError
from app.services.telemetry import collector as module
from app.services.telemetry.collector import TelemetryCollector, read_message, sensor_state
from app.services.telemetry.store import TelemetryStore, naive

ENTITY = "sensor.room_temperature"
MOTION = "binary_sensor.hall_motion"
SECRET = "private-ha-attribute-should-not-be-stored"


def state(value="21.5", entity=ENTITY, second=0):
    return {
        "entity_id": entity,
        "state": value,
        "attributes": {
            "unit_of_measurement": "°C",
            "device_class": "temperature",
            "friendly_name": SECRET,
            "private": SECRET,
        },
        "last_changed": f"2026-10-18T01:00:{second:02d}Z",
        "last_updated": f"2026-10-18T01:00:{second:02d}Z",
    }


def event(value=None, entity=ENTITY, second=1):
    return {
        "id": 1,
        "type": "event",
        "event": {
            "event_type": "state_changed",
            "time_fired": f"2026-10-18T01:00:{second:02d}Z",
            "data": {"entity_id": entity, "new_state": value, "old_state": {"private": SECRET}},
            "context": {"user_id": SECRET},
        },
    }


class FakeWS:
    def __init__(self, states, *, auth="auth_ok", sync_events=(), pong=True):
        self.states = states
        self.auth = auth
        self.sync_events = sync_events
        self.pong = pong
        self.incoming = asyncio.Queue()
        self.incoming.put_nowait({"type": "auth_required"})
        self.sent = []
        self.closed = False

    async def send(self, raw):
        message = json.loads(raw)
        self.sent.append(message)
        match message["type"]:
            case "auth":
                assert message["access_token"] == settings.ha_token
                await self.incoming.put({"type": self.auth, "message": SECRET})
            case "subscribe_events":
                assert message["event_type"] == "state_changed"
                await self.incoming.put({"type": "result", "id": message["id"], "success": True})
            case "get_states":
                for item in self.sync_events:
                    await self.incoming.put(item)
                await self.incoming.put(
                    {"type": "result", "id": message["id"], "success": True, "result": self.states}
                )
            case "ping":
                if self.pong:
                    await self.incoming.put({"type": "pong", "id": message["id"]})
            case _:
                raise AssertionError("Сборщик не должен вызывать команды HA")

    async def recv(self):
        value = await self.incoming.get()
        if isinstance(value, Exception):
            raise value
        return json.dumps(value)


@pytest.fixture
def telemetry_socket(monkeypatch):
    monkeypatch.setattr(settings, "ha_telemetry_entities", [ENTITY, MOTION])
    sockets = []
    snapshots = [[state(), state("off", MOTION)]]

    @asynccontextmanager
    async def connection():
        ws = FakeWS(copy.deepcopy(snapshots[min(len(sockets), len(snapshots) - 1)]))
        sockets.append(ws)
        try:
            yield ws
        finally:
            ws.closed = True

    monkeypatch.setattr(module, "socket_connection", connection)
    return sockets, snapshots


@pytest.fixture
def telemetry_client(telemetry_socket, client):
    wait(client, lambda: client.app.state.telemetry.status == "connected")
    return client


def wait(client, condition, timeout=4):
    async def poll():
        async with asyncio.timeout(timeout):
            while not condition():
                await asyncio.sleep(0.005)

    client.portal.call(poll)


def enqueue(client, sockets, message):
    client.portal.call(sockets[-1].incoming.put, message)


def rows(client, model):
    async def read():
        async with base.async_session() as session:
            return (await session.scalars(select(model))).all()

    return client.portal.call(read)


def wait_gap(client):
    async def poll():
        async with asyncio.timeout(2):
            while True:
                async with base.async_session() as session:
                    gap = await session.scalar(
                        select(TelemetryGap).where(TelemetryGap.ended_at.is_(None))
                    )
                    if gap:
                        return
                await asyncio.sleep(0.005)

    client.portal.call(poll)


def test_disabled_no_network_and_authenticated_routes(client, auth_headers):
    for route in ("/telemetry", "/telemetry/history", "/telemetry/gaps"):
        assert client.get("/api/v1" + route).status_code == 401
        assert client.get("/api/v1" + route, headers=auth_headers).status_code == 200
    body = client.get("/api/v1/telemetry", headers=auth_headers).json()
    assert body["status"] == "disabled"
    assert body["states"] == []
    assert body["last_confirmed_at"] is None
    assert len(rows(client, TelemetryGap)) == 1


def test_snapshot_live_dedupe_filter_remove(telemetry_client, telemetry_socket, auth_headers):
    client = telemetry_client
    sockets, _ = telemetry_socket
    baseline = rows(client, SensorHistory)
    assert len(baseline) == 2
    assert all(row.source == "ha_snapshot" and row.ha_timestamp is None for row in baseline)
    assert all(SECRET not in row.attributes_json for row in baseline)
    assert rows(client, TelemetryGap)[0].ended_at is not None
    checkpoint = rows(client, TelemetryCheckpoint)[0].last_seen
    enqueue(client, sockets, event(state("22", second=1)))
    wait(client, lambda: client.app.state.telemetry.current[ENTITY].state == "22")
    enqueue(client, sockets, event(state("22", second=1)))
    enqueue(client, sockets, event({"state": SECRET}, "sensor.unselected", 2))
    enqueue(client, sockets, event(None, MOTION, 2))
    wait(client, lambda: client.app.state.telemetry.current[MOTION] is None)
    history = client.get("/api/v1/telemetry/history", headers=auth_headers).json()
    assert history["total"] == 4
    assert history["items"][0]["state"] is None
    live = history["items"][1]
    assert live["source"] == "ha_state_changed"
    assert live["ha_timestamp"] == "2026-10-18T01:00:01.000000Z"
    assert SECRET not in json.dumps(history)
    assert rows(client, TelemetryCheckpoint)[0].last_seen == checkpoint
    assert len(rows(client, DeviceState)) == 1
    result = client.get("/api/v1/telemetry", headers=auth_headers).json()
    assert result["states"][0]["stale"] is False
    assert result["states"][1]["present"] is False


def test_reconnect_snapshot_gap_and_missing_entity(
    telemetry_client, telemetry_socket, auth_headers
):
    client = telemetry_client
    sockets, snapshots = telemetry_socket
    snapshots.append([state("28", second=20)])
    enqueue(client, sockets, OSError(SECRET))
    wait(client, lambda: client.app.state.telemetry.status == "disconnected")
    assert client.get("/api/v1/telemetry", headers=auth_headers).json()["states"][0]["stale"]
    wait(client, lambda: len(sockets) == 2 and client.app.state.telemetry.status == "connected")
    assert sockets[0].closed
    assert client.app.state.telemetry.current[ENTITY].state == "28"
    assert client.app.state.telemetry.current[MOTION] is None
    assert len(rows(client, SensorHistory)) == 4
    gaps = rows(client, TelemetryGap)
    assert len(gaps) == 2 and all(row.ended_at for row in gaps)
    assert gaps[-1].reason == "HA_UNAVAILABLE"
    assert all(row.source == "ha_snapshot" for row in rows(client, SensorHistory))
    assert all(msg["type"] in {"auth", "subscribe_events", "get_states"} for msg in sockets[1].sent)


def test_storage_failure_does_not_advance_cache(telemetry_client, telemetry_socket, monkeypatch):
    client = telemetry_client
    sockets, _ = telemetry_socket
    collector = client.app.state.telemetry
    original = collector.store.write
    monkeypatch.setattr(collector.store, "write", AsyncMock(side_effect=SQLAlchemyError(SECRET)))
    enqueue(client, sockets, event(state("99", second=1)))
    wait(client, lambda: collector.error == "STORAGE_ERROR")
    assert collector.current[ENTITY].state == "21.5"
    assert rows(client, DeviceState)[0].state == "21.5"
    assert len(rows(client, SensorHistory)) == 2
    assert rows(client, TelemetryGap)[-1].ended_at is None
    monkeypatch.setattr(collector.store, "write", original)
    wait(client, lambda: len(sockets) == 2 and collector.status == "connected")


def test_history_pagination_validation(telemetry_client, auth_headers):
    client = telemetry_client
    url = "/api/v1/telemetry/history"
    page = client.get(url + "?limit=1", headers=auth_headers).json()
    assert page["total"] == 2 and len(page["items"]) == 1
    other = client.get(url + "?limit=1&offset=1", headers=auth_headers).json()
    assert page["items"][0]["id"] > other["items"][0]["id"]
    assert (
        client.get(url + "?entity_id=sensor.unselected", headers=auth_headers).json()["total"] == 0
    )
    for query in ("limit=101", "offset=-1", "entity_id=private-secret/%"):
        response = client.get(url + "?" + query, headers=auth_headers)
        assert response.status_code == 422 and "private-secret" not in response.text


def test_retention_row_limit_and_deselection(telemetry_client, monkeypatch):
    client = telemetry_client
    store = client.app.state.telemetry.store
    monkeypatch.setattr(settings, "sensor_history_max_rows", 3)

    async def scenario():
        for second in range(1, 6):
            await store.write({ENTITY: sensor_state(state(str(second), second=second), ENTITY)})

    client.portal.call(scenario)
    history = rows(client, SensorHistory)
    assert len(history) == 3
    assert [row.state for row in history] == ["3", "4", "5"]
    monkeypatch.setattr(clock, "utcnow", lambda: datetime.now(UTC) + timedelta(days=91))
    client.portal.call(store.checkpoint)
    assert rows(client, SensorHistory) == []
    other = TelemetryStore(())
    client.portal.call(other.gap, "DISABLED")
    assert rows(client, DeviceState) == []


def test_restart_recovers_gap_without_fabricated_events(telemetry_client):
    client = telemetry_client
    collector = client.app.state.telemetry
    checkpoint = rows(client, TelemetryCheckpoint)[0].last_seen
    client.portal.call(collector.stop)
    gaps = rows(client, TelemetryGap)
    assert gaps[-1].started_at == checkpoint and gaps[-1].ended_at is None
    replacement = TelemetryCollector()
    client.portal.call(replacement.start)
    wait(client, lambda: replacement.status == "connected")
    client.portal.call(replacement.stop)
    assert len(rows(client, SensorHistory)) == 4
    assert all(row.source == "ha_snapshot" for row in rows(client, SensorHistory))
    assert len(rows(client, TelemetryGap)) == 3


@pytest.mark.parametrize("raw", ["[]", "null", '{"type":NaN}', b"{}", '{"type":1}', "{"])
def test_bad_protocol_without_input_leak(raw):
    with pytest.raises(HAError, match="HA_BAD_RESPONSE"):
        read_message(raw)


@pytest.mark.parametrize(
    "value,entity",
    [(SECRET, ENTITY), ("nan", ENTITY), ("inf", ENTITY), ("21", MOTION), ("true", MOTION)],
)
def test_only_numeric_and_binary_states(value, entity):
    with pytest.raises(HAError, match="HA_BAD_SENSOR_STATE"):
        sensor_state(state(value, entity), entity)


@pytest.mark.parametrize(
    "entities", [["person.kirill"], ["sensor.foo/bar"], ["sensor."], [ENTITY] * 101]
)
def test_selection_validation(entities):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(_env_file=None, ha_telemetry_entities=entities)


@pytest.mark.asyncio
async def test_auth_failure_and_sync_overflow():
    collector = TelemetryCollector()
    with pytest.raises(HAError, match="HA_AUTH_FAILED"):
        await collector.session(FakeWS([], auth="auth_invalid"))
    with pytest.raises(HAError, match="HA_SYNC_OVERFLOW"):
        await collector.session(FakeWS([], sync_events=[event()] * 256))


@pytest.mark.asyncio
async def test_connection_options_and_redirect(monkeypatch):
    connection_class = module.LocalConnect
    options = {}

    def create(uri, **kwargs):
        options.update(uri=uri, **kwargs)

    monkeypatch.setattr(module, "LocalConnect", create)
    monkeypatch.setattr(settings, "ha_base_url", "https://ha.test:8123")
    module.socket_connection()
    assert options["uri"] == "wss://ha.test:8123/api/websocket"
    assert options["proxy"] is None and options["compression"] is None
    assert options["max_size"] == 2 * 1024 * 1024 and options["max_queue"] == 16
    exc = OSError(SECRET)
    # Метод исходного класса не требует инициализации сокета.
    assert connection_class.process_redirect(None, exc) is exc


def test_heartbeat_checkpoint_and_timeout(telemetry_client, telemetry_socket, monkeypatch):
    client = telemetry_client
    sockets, _ = telemetry_socket
    collector = client.app.state.telemetry
    # Новая сессия читает уменьшенный только в тесте интервал.
    monkeypatch.setattr(module, "HEARTBEAT", 0.02)
    monkeypatch.setattr(settings, "ha_timeout_seconds", 0.1)
    enqueue(client, sockets, OSError("synthetic drop"))
    wait(client, lambda: len(sockets) == 2 and collector.status == "connected")
    checkpoint = rows(client, TelemetryCheckpoint)[0].last_seen
    wait(client, lambda: any(msg["type"] == "ping" for msg in sockets[-1].sent))
    wait(client, lambda: sum(msg["type"] == "ping" for msg in sockets[-1].sent) >= 2)
    assert rows(client, TelemetryCheckpoint)[0].last_seen > checkpoint
    sockets[-1].pong = False
    wait(client, lambda: collector.error == "HA_TIMEOUT")
    wait_gap(client)
    assert rows(client, TelemetryGap)[-1].ended_at is None


def test_unclean_restart_uses_last_durable_checkpoint(telemetry_client):
    client = telemetry_client
    collector = client.app.state.telemetry

    async def crash():
        collector.task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await collector.task

    client.portal.call(crash)
    checkpoint = rows(client, TelemetryCheckpoint)[0].last_seen
    assert all(row.ended_at for row in rows(client, TelemetryGap))
    replacement = TelemetryCollector()
    client.portal.call(replacement.store.gap, "CORE_START")
    assert rows(client, TelemetryGap)[-1].started_at == checkpoint
    assert rows(client, TelemetryGap)[-1].ended_at is None
    assert len(rows(client, SensorHistory)) == 2


def test_gap_limit_is_bounded(telemetry_client):
    client = telemetry_client

    async def seed():
        now = naive(clock.utcnow())
        async with base.async_session() as session, session.begin():
            session.add_all(
                TelemetryGap(started_at=now, ended_at=now, reason="SYNTHETIC") for _ in range(1005)
            )
        await client.app.state.telemetry.store.gap("SYNTHETIC")

    client.portal.call(seed)
    assert len(rows(client, TelemetryGap)) == 1000
    assert rows(client, TelemetryGap)[-1].ended_at is None


def test_order_error_and_unknown_unavailable(telemetry_client, telemetry_socket):
    client = telemetry_client
    sockets, _ = telemetry_socket
    collector = client.app.state.telemetry
    enqueue(client, sockets, event(state("unknown", second=10), second=10))
    wait(client, lambda: collector.current[ENTITY].state == "unknown")
    enqueue(client, sockets, event(state("unavailable", second=11), second=11))
    wait(client, lambda: collector.current[ENTITY].state == "unavailable")
    enqueue(client, sockets, event(state("22", second=2), second=2))
    wait(client, lambda: collector.error == "HA_STATE_ORDER")
    assert collector.current[ENTITY].state == "unavailable"


def test_sync_events_are_covered_by_gap_not_fabricated(telemetry_client):
    client = telemetry_client
    collector = client.app.state.telemetry

    async def scenario():
        await collector.stop()
        ws = FakeWS([state("30", second=10)], sync_events=[event(state("25", second=5), second=5)])
        task = asyncio.create_task(collector.session(ws))
        async with asyncio.timeout(2):
            while collector.status != "connected":
                await asyncio.sleep(0.005)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    client.portal.call(scenario)
    assert collector.current[ENTITY].state == "30"
    assert all(row.state != "25" for row in rows(client, SensorHistory))
    assert rows(client, TelemetryGap)[-1].ended_at is not None
