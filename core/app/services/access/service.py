import asyncio
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.core import clock
from app.core.config import settings
from app.db import base
from app.db.models import AccessGate, AccessGrant, NotificationRaw
from app.schemas import NotificationIn
from app.services.ha_bridge.audit import execute_command
from app.services.notification.extraction import ExtractedNotification
from app.services.notification.privacy import allowed_apps, can_store
from app.services.notification.store import identity
from app.services.telemetry.store import iso, naive


class AccessError(Exception):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code, self.status = code, status


def policy():
    value = dict(
        version=1,
        enabled=settings.access_enabled,
        allowed_locks=sorted(settings.access_allowed_locks),
        source_apps=sorted(allowed_apps()),
        max_minutes=15,
        one_use=True,
        owner_confirmation=True,
        adapter="shade_keypad",
    )
    # Ротация любого ключа отзывает прежние разрешения, ключи не публикуются.
    key_scope = hmac.digest(
        settings.api_key.encode(),
        b"ShadeAccessPolicy-v1:" + settings.access_keypad_token.encode(),
        "sha256",
    ).hex()
    scope = hashlib.sha256((json.dumps(value, sort_keys=True) + key_scope).encode()).hexdigest()
    return value, scope


def digest(grant_id, pin):
    return hmac.digest(
        settings.api_key.encode(), f"ShadeAccessPIN-v1:{grant_id}:{pin}".encode(), "sha256"
    ).hex()


def fingerprint(entity, pin):
    return hmac.digest(
        settings.api_key.encode(), f"ShadeAccessHistory-v1:{entity}:{pin}".encode(), "sha256"
    ).hex()


def payload(row, pin=None):
    return dict(
        id=row.id,
        notification_id=row.notification_id,
        entity_id=row.entity_id,
        policy_scope=row.policy_scope,
        duration_minutes=row.duration_minutes,
        state=row.state,
        error_code=row.error_code,
        event_id=row.event_id,
        new_state=row.new_state,
        state_observed=bool(row.state_observed),
        created_at=iso(row.created_at),
        expires_at=iso(row.expires_at),
        updated_at=iso(row.updated_at),
        pin=pin,
    )


def source_hash(row, now):
    if (
        row is None
        or row.processing_status != "processed"
        or row.category != "delivery"
        or not row.payload_hash
        or not row.dedupe_key
        or not can_store(row.app_name, row.title, row.text)
        or not now - timedelta(hours=24) <= row.created_at <= now
    ):
        return None
    try:
        extracted = ExtractedNotification.model_validate_json(row.extracted_data_json or "")
        item = NotificationIn(
            app_name=row.app_name,
            title=row.title,
            text=row.text,
            timestamp=row.timestamp,
            priority=row.priority,
        )
        stamp = datetime.fromisoformat(row.timestamp.replace("Z", "+00:00"))
        if stamp.tzinfo is None or not now - timedelta(hours=24) <= naive(stamp) <= now:
            return None
        if extracted.category != "delivery" or identity(item)[1] != row.payload_hash:
            return None
    except (ValidationError, ValueError, TypeError, RecursionError):
        return None
    return row.payload_hash


class AccessService:
    def __init__(self, client):
        self.client = client
        self.closed = False
        self.lock = asyncio.Lock()
        self.deadlines = {}

    @property
    def status(self):
        return "closed" if self.closed else "ready" if settings.access_enabled else "disabled"

    def enabled(self):
        if self.closed or not settings.access_enabled:
            raise AccessError("ACCESS_DISABLED", 503)

    async def start(self):
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            # После простоя не восстанавливать доступ при неизвестной истории часов/двери.
            for old, state in (("active", "revoked"), ("dispatching", "unknown")):
                await session.execute(
                    update(AccessGrant)
                    .where(AccessGrant.state == old)
                    .values(
                        state=state,
                        error_code="ACCESS_CORE_RESTARTED",
                        updated_at=naive(clock.utcnow()),
                        pin_digest="",
                    )
                )
            await self.refresh(session)

    async def close(self):
        self.closed = True
        async with self.lock:
            pass

    async def refresh(self, session):
        now = naive(clock.utcnow())
        rows = list(await session.scalars(select(AccessGrant).where(AccessGrant.state == "active")))
        for key in set(self.deadlines) - {row.id for row in rows}:
            self.deadlines.pop(key, None)
        for row in rows:
            if row.expires_at <= now or time.monotonic() >= self.deadlines.get(row.id, 0):
                row.state, row.error_code = "expired", "ACCESS_EXPIRED"
            elif (
                row.created_at > now
                or row.policy_scope != policy()[1]
                or row.entity_id not in settings.access_allowed_locks
                or not settings.access_enabled
                or source_hash(await session.get(NotificationRaw, row.notification_id), now)
                != row.source_hash
            ):
                row.state, row.error_code = "revoked", "ACCESS_CONTEXT_CHANGED"
            if row.state != "active":
                row.pin_digest, row.updated_at = "", now
                self.deadlines.pop(row.id, None)
        await session.execute(
            delete(AccessGrant).where(
                AccessGrant.created_at < now - timedelta(days=90),
                AccessGrant.state.not_in(["active", "dispatching"]),
            )
        )
        await session.execute(
            delete(AccessGate).where(AccessGate.entity_id.not_in(settings.access_allowed_locks))
        )
        await session.flush()

    async def descriptor(self):
        value, scope = policy()
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            await self.refresh(session)
            rows = list(
                await session.scalars(
                    select(AccessGrant)
                    .order_by(AccessGrant.created_at.desc(), AccessGrant.id)
                    .limit(50)
                )
            )
            return value | dict(policy_scope=scope, grants=[payload(row) for row in rows])

    async def get(self, grant_id):
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            await self.refresh(session)
            row = await session.get(AccessGrant, grant_id)
            if row is None:
                raise AccessError("ACCESS_NOT_FOUND", 404)
            return payload(row)

    async def create(self, notification_id, entity, minutes, scope):
        self.enabled()
        if type(minutes) is not int or not 1 <= minutes <= 15:
            raise AccessError("ACCESS_BAD_WINDOW", 422)
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            await self.refresh(session)
            if scope != policy()[1] or entity not in settings.access_allowed_locks:
                raise AccessError("ACCESS_POLICY_CHANGED")
            now = naive(clock.utcnow())
            source = await session.get(NotificationRaw, notification_id)
            hashed = source_hash(source, now)
            if hashed is None:
                raise AccessError("ACCESS_DELIVERY_NOT_ELIGIBLE")
            old = await session.scalar(
                select(AccessGrant).where(
                    or_(
                        AccessGrant.notification_id == notification_id,
                        AccessGrant.source_hash == hashed,
                    )
                )
            )
            if old is not None:
                if (old.entity_id, old.duration_minutes, old.policy_scope) != (
                    entity,
                    minutes,
                    scope,
                ):
                    raise AccessError("ACCESS_ID_CONFLICT")
                return payload(old)
            if await session.scalar(
                select(AccessGrant.id).where(
                    AccessGrant.entity_id == entity,
                    AccessGrant.state.in_(["active", "dispatching", "unknown"]),
                )
            ):
                raise AccessError("ACCESS_LOCK_BUSY")
            if await session.scalar(select(func.count()).select_from(AccessGrant)) >= 1000:
                raise AccessError("ACCESS_CAPACITY")
            grant_id = str(uuid4())
            for _ in range(32):
                pin = f"{secrets.randbelow(1_000_000):06d}"
                pin_history = fingerprint(entity, pin)
                if not await session.scalar(
                    select(AccessGrant.id).where(AccessGrant.pin_fingerprint == pin_history)
                ):
                    break
            else:
                raise AccessError("ACCESS_RANDOM_COLLISION", 503)
            row = AccessGrant(
                id=grant_id,
                notification_id=notification_id,
                source_hash=hashed,
                policy_scope=scope,
                entity_id=entity,
                duration_minutes=minutes,
                pin_digest=digest(grant_id, pin),
                pin_fingerprint=pin_history,
                state="active",
                error_code=None,
                event_id=None,
                new_state=None,
                state_observed=0,
                bad_attempts=0,
                created_at=now,
                expires_at=now + timedelta(minutes=minutes),
                updated_at=now,
            )
            session.add(row)
            await session.flush()
            self.deadlines[grant_id] = time.monotonic() + minutes * 60
            return payload(row, pin)

    async def revoke(self, grant_id, checked=False):
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            await self.refresh(session)
            row = await session.get(AccessGrant, grant_id)
            if row is None:
                raise AccessError("ACCESS_NOT_FOUND", 404)
            if row.state == "dispatching":
                raise AccessError("ACCESS_IN_FLIGHT")
            if row.state == "unknown" and not checked:
                raise AccessError("ACCESS_MANUAL_CHECK_REQUIRED")
            if row.state in {"active", "unknown"}:
                row.state, row.pin_digest, row.updated_at = "revoked", "", naive(clock.utcnow())
                row.error_code = "ACCESS_USER_REVOKED"
            return payload(row)

    async def verify(self, entity, pin):
        self.enabled()
        # Single-flight на процесс; SQLite claim защищает от повторного потребления.
        if self.lock.locked():
            raise AccessError("ACCESS_BUSY", 429)
        async with self.lock:
            self.enabled()
            denied = True
            async with base.async_session() as session, session.begin():
                await session.connection(execution_options={"sqlite_immediate": True})
                await self.refresh(session)
                now = naive(clock.utcnow())
                if entity not in settings.access_allowed_locks:
                    raise AccessError("ACCESS_DENIED", 403)
                gate = await session.get(AccessGate, entity)
                if gate is None:
                    gate = AccessGate(entity_id=entity, window_start=now, attempts=0)
                    session.add(gate)
                if now >= gate.window_start + timedelta(seconds=60):
                    gate.window_start, gate.attempts = now, 0
                if now < gate.window_start or gate.attempts >= 5:
                    raise AccessError("ACCESS_RATE_LIMITED", 429)
                gate.attempts += 1
                row = await session.scalar(
                    select(AccessGrant).where(
                        AccessGrant.entity_id == entity, AccessGrant.state == "active"
                    )
                )
                if row is not None:
                    if hmac.compare_digest(row.pin_digest, digest(row.id, pin)):
                        row.state, row.pin_digest, row.updated_at = "dispatching", "", now
                        grant_id, denied = row.id, False
                    else:
                        row.bad_attempts += 1
                        if row.bad_attempts >= 5:
                            row.state, row.pin_digest = "revoked", ""
                            row.error_code, row.updated_at = "ACCESS_ATTEMPTS_EXHAUSTED", now
            # Нельзя выбрасывать ошибку внутри транзакции: откатился бы счётчик попыток.
            if denied:
                raise AccessError("ACCESS_DENIED", 403)
            return await self.dispatch(grant_id, entity)

    async def dispatch(self, grant_id, entity):
        state, error, event_id, new_state, observed = "unknown", "ACCESS_UNKNOWN", None, None, False
        try:
            async with base.async_session() as session:
                result = await execute_command(session, self.client, "lock", "unlock", entity, {})
            state, error, event_id = "used", None, result["event_id"]
            new_state = (
                result["new_state"]
                if result["new_state"]
                in {
                    "locked",
                    "unlocked",
                    "locking",
                    "unlocking",
                    "open",
                    "opening",
                    "jammed",
                    "unknown",
                    "unavailable",
                }
                else None
            )
            observed = result["state_observed"] and new_state is not None
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            event_id = detail.get("event_id")
            state = "failed" if detail.get("outcome") in {"not_sent", "rejected"} else "unknown"
            error = (
                "ACCESS_NOT_SENT"
                if detail.get("outcome") == "not_sent"
                else ("ACCESS_HA_REJECTED" if state == "failed" else "ACCESS_UNKNOWN")
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        try:
            async with base.async_session() as session, session.begin():
                await session.connection(execution_options={"sqlite_immediate": True})
                await session.execute(
                    update(AccessGrant)
                    .where(AccessGrant.id == grant_id, AccessGrant.state == "dispatching")
                    .values(
                        state=state,
                        error_code=error,
                        event_id=event_id,
                        new_state=new_state,
                        state_observed=int(observed),
                        updated_at=naive(clock.utcnow()),
                    )
                )
        except SQLAlchemyError:
            raise AccessError("ACCESS_RESULT_UNCONFIRMED", 503) from None
        return await self.get(grant_id)
