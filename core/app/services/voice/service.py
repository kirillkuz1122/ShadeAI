import asyncio
import hashlib
import json
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.core import clock
from app.core.config import settings
from app.db import base
from app.db.models import VoiceRequest
from app.services.ha_bridge.audit import execute_command
from app.services.telemetry.store import iso, naive
from app.services.voice.audio import payload_digest, read_pcm
from app.services.voice.engine import STTEngine
from app.services.voice.errors import VoiceError
from app.services.voice.intent import command, normalize

TERMINAL = {"accepted", "failed", "unknown", "cancelled", "expired"}


def policy():
    value = dict(
        version=1,
        enabled=settings.voice_enabled,
        targets=settings.voice_targets,
        ttl_seconds=60,
        model_manifest=settings.voice_model_manifest_sha256,
        max_audio_seconds=10,
        confirmation=True,
    )
    scope = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return value, scope


def payload(row, transcription=None):
    return dict(
        id=row.id,
        policy_scope=row.policy_scope,
        entity_id=row.entity_id,
        action=row.action,
        alias=row.alias,
        state=row.state,
        error_code=row.error_code,
        event_id=row.event_id,
        new_state=row.new_state,
        state_observed=bool(row.state_observed),
        created_at=iso(row.created_at),
        expires_at=iso(row.expires_at),
        updated_at=iso(row.updated_at),
        transcription=transcription,
    )


class VoiceService:
    def __init__(self, client, engine=None):
        self.client = client
        self.engine = engine or STTEngine()
        self.lock = asyncio.Lock()
        self.closed = False

    @property
    def status(self):
        if self.closed:
            return "closed"
        if not settings.voice_enabled:
            return "disabled"
        if self.lock.locked():
            return "busy"
        return "configured" if self.engine.configured() else "not_configured"

    async def prune(self, session):
        now = naive(clock.utcnow())
        await session.execute(
            update(VoiceRequest)
            .where(VoiceRequest.state == "pending", VoiceRequest.expires_at <= now)
            .values(state="expired", updated_at=now, error_code="VOICE_EXPIRED")
        )
        await session.execute(
            delete(VoiceRequest).where(
                VoiceRequest.created_at < now - timedelta(days=7), VoiceRequest.state.in_(TERMINAL)
            )
        )

    async def start(self):
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            for old, new in (("pending", "cancelled"), ("dispatching", "unknown")):
                await session.execute(
                    update(VoiceRequest)
                    .where(VoiceRequest.state == old)
                    .values(
                        state=new,
                        error_code="VOICE_CORE_RESTARTED",
                        updated_at=naive(clock.utcnow()),
                    )
                )
            await self.prune(session)

    async def close(self):
        self.closed = True
        await self.engine.close()
        async with self.lock:
            pass

    def enabled(self):
        if self.closed:
            raise VoiceError("VOICE_CLOSED", 503)
        if not settings.voice_enabled:
            raise VoiceError("VOICE_DISABLED", 503)

    async def descriptor(self):
        value, scope = policy()
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            await self.prune(session)
            rows = list(
                (
                    await session.scalars(
                        select(VoiceRequest).order_by(VoiceRequest.created_at.desc()).limit(20)
                    )
                ).all()
            )
        return dict(
            version=1,
            enabled=value["enabled"],
            policy_scope=scope,
            stt_available=self.engine.configured(),
            stt_status=self.status,
            max_audio_seconds=10,
            requires_confirmation=True,
            targets=[dict(alias=k, entity_id=v) for k, v in value["targets"].items()],
            requests=[payload(r) for r in rows],
        )

    async def get(self, identity):
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            await self.prune(session)
            row = await session.get(VoiceRequest, identity)
            if row is None:
                raise VoiceError("VOICE_REQUEST_NOT_FOUND", 404)
            return payload(row)

    async def previous(self, identity, digest, scope):
        async with base.async_session() as session:
            row = await session.get(VoiceRequest, identity)
            if row is None:
                return None
            if row.payload_hash != digest:
                raise VoiceError("VOICE_ID_CONFLICT", 409)
            if row.policy_scope != scope:
                raise VoiceError("VOICE_POLICY_CHANGED", 409)
        return await self.get(identity)

    async def prepare(self, identity, data, source):
        self.enabled()
        value, scope = policy()
        digest = payload_digest(source, data)
        previous = await self.previous(identity, digest, scope)
        if previous is not None:
            return previous
        if source == "wav":
            await asyncio.to_thread(read_pcm, data)
            result = await self.engine.transcribe(data)
            if result.confidence < 0.8:
                raise VoiceError("VOICE_UNRECOGNIZED")
            text = result.text
        else:
            text = data.decode("utf-8")
        entity, action, alias = command(text, value["targets"])
        # Повторная проверка после CPU/STT, транзакции до этого не удерживались.
        self.enabled()
        if policy()[1] != scope:
            raise VoiceError("VOICE_POLICY_CHANGED", 409)
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            old = await session.get(VoiceRequest, identity)
            if old is not None:
                if old.payload_hash != digest:
                    raise VoiceError("VOICE_ID_CONFLICT", 409)
                return payload(old)
            await self.prune(session)
            if await session.scalar(select(func.count()).select_from(VoiceRequest)) >= 1000:
                raise VoiceError("VOICE_CAPACITY", 409)
            now = naive(clock.utcnow())
            row = VoiceRequest(
                id=identity,
                payload_hash=digest,
                policy_scope=scope,
                entity_id=entity,
                action=action,
                alias=alias,
                state="pending",
                error_code=None,
                event_id=None,
                new_state=None,
                state_observed=0,
                created_at=now,
                expires_at=now + timedelta(seconds=60),
                updated_at=now,
            )
            session.add(row)
            await session.flush()
            return payload(row, normalize(text))

    async def cancel(self, identity):
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            row = await session.get(VoiceRequest, identity)
            if row is None:
                raise VoiceError("VOICE_REQUEST_NOT_FOUND", 404)
            if row.state == "dispatching":
                raise VoiceError("VOICE_IN_FLIGHT", 409)
            if row.state == "pending":
                row.state, row.error_code, row.updated_at = (
                    "cancelled",
                    "VOICE_USER_CANCELLED",
                    naive(clock.utcnow()),
                )
            return payload(row)

    async def confirm(self, identity, scope):
        self.enabled()
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            row = await session.get(VoiceRequest, identity)
            if row is None:
                raise VoiceError("VOICE_REQUEST_NOT_FOUND", 404)
            if row.policy_scope != scope or scope != policy()[1]:
                raise VoiceError("VOICE_POLICY_CHANGED", 409)
            if row.state in TERMINAL:
                return payload(row)
            if row.state != "pending":
                raise VoiceError("VOICE_IN_FLIGHT", 409)
            if row.expires_at <= naive(clock.utcnow()) or row.created_at > naive(clock.utcnow()):
                raise VoiceError("VOICE_EXPIRED", 409)
            if settings.voice_targets.get(row.alias) != row.entity_id or row.action not in {
                "turn_on",
                "turn_off",
            }:
                raise VoiceError("VOICE_POLICY_CHANGED", 409)
            row.state, row.updated_at = "dispatching", naive(clock.utcnow())
            entity, action = row.entity_id, row.action
        state, error, event_id, new_state, observed = "unknown", "VOICE_UNKNOWN", None, None, False
        try:
            async with base.async_session() as session:
                result = await execute_command(session, self.client, "light", action, entity, {})
            state, error, event_id = "accepted", None, result["event_id"]
            new_state = (
                result["new_state"]
                if result["new_state"] in {"on", "off", "unknown", "unavailable"}
                else None
            )
            observed = result["state_observed"] and new_state is not None
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            event_id = detail.get("event_id")
            # Ошибка фиксации аудита может быть уже после команды: тогда unknown.
            state = "failed" if detail.get("outcome") in {"not_sent", "rejected"} else "unknown"
            error = (
                "VOICE_NOT_SENT"
                if detail.get("outcome") == "not_sent"
                else "VOICE_HA_REJECTED"
                if state == "failed"
                else "VOICE_UNKNOWN"
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        try:
            async with base.async_session() as session, session.begin():
                await session.connection(execution_options={"sqlite_immediate": True})
                await session.execute(
                    update(VoiceRequest)
                    .where(VoiceRequest.id == identity, VoiceRequest.state == "dispatching")
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
            raise VoiceError("VOICE_RESULT_UNCONFIRMED", 503) from None
        return await self.get(identity)
