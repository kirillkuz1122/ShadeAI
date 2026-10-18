import asyncio
import json
import logging
import math
import random
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from pydantic import AwareDatetime, TypeAdapter, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus, WebSocketException

from app.core.config import settings
from app.services.ha_bridge.client import HAError, reject_constant
from app.services.ha_bridge.models import HAState
from app.services.telemetry.store import TelemetryStore, attributes

MAX_MESSAGE = 2 * 1024 * 1024
HEARTBEAT = 30.0
logger = logging.getLogger("shade")
wire_logger = logging.Logger("shade.telemetry.wire", level=logging.CRITICAL + 1)
wire_logger.addHandler(logging.NullHandler())
wire_logger.propagate = False


class LocalConnect(connect):
    # Bearer отправляется в JSON после handshake: любой redirect должен быть запрещён.
    def process_redirect(self, exc: Exception) -> Exception:
        return exc


def socket_connection():
    url = urlsplit(settings.ha_base_url)
    uri = urlunsplit(
        ("wss" if url.scheme == "https" else "ws", url.netloc, "/api/websocket", "", "")
    )
    return LocalConnect(
        uri,
        proxy=None,
        compression=None,
        open_timeout=settings.ha_timeout_seconds,
        close_timeout=2,
        ping_interval=20,
        ping_timeout=10,
        max_size=MAX_MESSAGE,
        max_queue=16,
        logger=wire_logger,
    )


def read_message(raw) -> dict:
    try:
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_MESSAGE:
            raise ValueError
        value = json.loads(raw, parse_constant=reject_constant)
        if not isinstance(value, dict) or not isinstance(value.get("type"), str):
            raise ValueError
        return value
    except (ValueError, RecursionError):
        raise HAError("HA_BAD_RESPONSE") from None


def sensor_state(raw, entity: str) -> HAState:
    try:
        state = HAState.model_validate(raw)
        if state.entity_id != entity:
            raise ValueError
        if state.state not in {"unknown", "unavailable"}:
            if entity.startswith("binary_sensor."):
                if state.state not in {"on", "off"}:
                    raise ValueError
            elif len(state.state) > 64 or not math.isfinite(float(state.state)):
                raise ValueError
        state.attributes = json.loads(attributes(state))
        return state
    except (ValueError, ValidationError):
        raise HAError("HA_BAD_SENSOR_STATE") from None


class TelemetryCollector:
    def __init__(self):
        self.entities = tuple(settings.ha_telemetry_entities)
        self.store = TelemetryStore(self.entities)
        self.status = "starting"
        self.error: str | None = None
        self.task: asyncio.Task | None = None
        self.current: dict[str, HAState | None] = {}
        self.ready_at = 0.0
        self.generation = 0

    async def start(self) -> None:
        await self.store.gap("CORE_START")
        self.task = asyncio.create_task(self.run(), name="ha-telemetry")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.status = "stopped"
        try:
            await self.store.gap("CORE_STOP")
        except SQLAlchemyError:
            logger.error("Telemetry STORAGE_ERROR")

    async def receive(self, ws) -> dict:
        return read_message(await ws.recv())

    async def result(self, ws, command_id: int) -> dict:
        for _ in range(256):
            message = await self.receive(ws)
            if message["type"] == "event" and message.get("id") == 1:
                # Время синхронизации целиком входит в gap; baseline берётся из get_states.
                continue
            if message["type"] != "result" or message.get("id") != command_id:
                raise HAError("HA_BAD_RESPONSE")
            if message.get("success") is not True:
                error = message.get("error")
                if isinstance(error, dict) and error.get("code") in {"unauthorized", "not_allowed"}:
                    raise HAError("HA_AUTH_FAILED")
                raise HAError("HA_SUBSCRIPTION_FAILED")
            return message
        raise HAError("HA_SYNC_OVERFLOW")

    async def session(self, ws) -> None:
        self.status = "syncing"
        async with asyncio.timeout(settings.ha_timeout_seconds):
            if (await self.receive(ws))["type"] != "auth_required":
                raise HAError("HA_BAD_RESPONSE")
            await ws.send(json.dumps({"type": "auth", "access_token": settings.ha_token}))
            auth = await self.receive(ws)
            if auth["type"] == "auth_invalid":
                raise HAError("HA_AUTH_FAILED")
            if auth["type"] != "auth_ok":
                raise HAError("HA_BAD_RESPONSE")
            await ws.send(
                json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"})
            )
            await self.result(ws, 1)
            await ws.send(json.dumps({"id": 2, "type": "get_states"}))
            raw = (await self.result(ws, 2)).get("result")
            if not isinstance(raw, list) or len(raw) > 5000:
                raise HAError("HA_BAD_RESPONSE")
            states = {}
            for item in raw:
                if not isinstance(item, dict):
                    raise HAError("HA_BAD_RESPONSE")
                entity = item.get("entity_id")
                if isinstance(entity, str) and entity in self.entities:
                    if entity in states:
                        raise HAError("HA_BAD_RESPONSE")
                    states[entity] = sensor_state(item, entity)
            self.current = {entity: states.get(entity) for entity in self.entities}
        await self.store.write(self.current, snapshot=True)
        self.generation += 1
        self.status, self.error = "connected", None
        loop = asyncio.get_running_loop()
        self.ready_at = loop.time()
        next_ping, pending, deadline, command_id = loop.time() + HEARTBEAT, None, 0.0, 2
        while True:
            now = loop.time()
            if pending is not None and now >= deadline:
                raise HAError("HA_TIMEOUT")
            if pending is None and now >= next_ping:
                command_id += 1
                pending, deadline = command_id, now + settings.ha_timeout_seconds
                await ws.send(json.dumps({"id": command_id, "type": "ping"}))
            timeout = max(0.001, (deadline if pending else next_ping) - loop.time())
            try:
                async with asyncio.timeout(timeout):
                    message = await self.receive(ws)
            except TimeoutError:
                continue
            if message["type"] == "pong" and message.get("id") == pending:
                await self.store.checkpoint()
                pending, next_ping = None, loop.time() + HEARTBEAT
            elif message["type"] == "event" and message.get("id") == 1:
                await self.event(message)
            else:
                raise HAError("HA_BAD_RESPONSE")

    async def event(self, message: dict) -> None:
        event = message.get("event")
        if not isinstance(event, dict) or event.get("event_type") != "state_changed":
            raise HAError("HA_BAD_RESPONSE")
        data = event.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("entity_id"), str):
            raise HAError("HA_BAD_RESPONSE")
        entity = data["entity_id"]
        if entity not in self.entities:
            return
        try:
            raw_time = event.get("time_fired")
            if not isinstance(raw_time, str):
                raise ValueError
            event_at: datetime = TypeAdapter(AwareDatetime).validate_python(raw_time)
        except (ValueError, ValidationError):
            raise HAError("HA_BAD_RESPONSE") from None
        if "new_state" not in data:
            raise HAError("HA_BAD_RESPONSE")
        state = sensor_state(data["new_state"], entity) if data["new_state"] is not None else None
        previous = self.current.get(entity)
        if previous and state:
            if state.last_updated < previous.last_updated:
                raise HAError("HA_STATE_ORDER")
            if (
                state.last_updated == previous.last_updated
                and state.state == previous.state
                and attributes(state) == attributes(previous)
            ):
                return
        elif previous is None and state is None:
            return
        await self.store.write({entity: state}, event_at=event_at)
        self.current[entity] = state

    async def run(self) -> None:
        delay = 1.0
        blocked = (
            "disabled" if not self.entities else "not_configured" if not settings.ha_token else None
        )
        while True:
            try:
                if blocked:
                    self.status = blocked
                    await self.store.gap(blocked.upper())
                    await asyncio.sleep(60)
                    continue
                self.status = "connecting"
                await self.store.gap("HA_RECONNECT")
                async with socket_connection() as ws:
                    await self.session(ws)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status = "disconnected"
                if isinstance(exc, HAError):
                    self.error = exc.code
                    if exc.code == "HA_AUTH_FAILED":
                        blocked = "auth_failed"
                elif isinstance(exc, SQLAlchemyError):
                    self.error = "STORAGE_ERROR"
                elif isinstance(exc, TimeoutError):
                    self.error = "HA_TIMEOUT"
                elif isinstance(exc, InvalidStatus) and exc.response.status_code in {401, 403}:
                    self.error, blocked = "HA_AUTH_FAILED", "auth_failed"
                elif isinstance(exc, (OSError, WebSocketException)):
                    self.error = "HA_UNAVAILABLE"
                else:
                    self.error = "TELEMETRY_ERROR"
                logger.warning("Telemetry %s", self.error)
                try:
                    await self.store.gap(self.error)
                except SQLAlchemyError:
                    self.error = "STORAGE_ERROR"
                if self.ready_at and asyncio.get_running_loop().time() - self.ready_at >= 60:
                    delay = 1.0
                self.ready_at = 0.0
                await asyncio.sleep(delay + random.uniform(0, delay / 5))
                delay = min(60.0, delay * 2)
