import asyncio
import json
from contextlib import suppress
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.core import clock
from app.core.config import settings
from app.db import base
from app.db.models import CalendarEvent, MeetingLease, MeetingLog, MeetingPlan
from app.services.calendar.service import digest
from app.services.ha_bridge.audit import execute_command
from app.services.ha_bridge.client import HAError
from app.services.ha_bridge.models import HAState
from app.services.suggestions.service import SuggestionError
from app.services.telemetry.store import naive


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class MeetingService:
    def __init__(self, calendar, client):
        self.calendar, self.client = calendar, client
        self.enabled = settings.meeting_mode_enabled
        self.allowed = tuple(settings.meeting_mode_allowed_switches)
        self.policy = dict(
            version=1,
            enabled=self.enabled,
            allowed_targets=list(self.allowed),
            max_duration_seconds=28800,
        )
        self.status = "starting" if self.enabled else "disabled"
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()

    def scope(self, event):
        return digest(
            [
                1,
                self.calendar.config_key,
                event.id,
                event.revision,
                event.starts_at.isoformat(),
                event.ends_at.isoformat(),
                self.policy,
            ]
        )

    def eligible(self, event, now):
        return (
            event is not None
            and event.config_key == self.calendar.config_key
            and event.status == "confirmed"
            and event.busy == 1
            and event.start_date is None
            and timedelta(0) < event.ends_at - event.starts_at <= timedelta(hours=8)
            and event.ends_at > now
        )

    def log(self, session, lease):
        session.add(
            MeetingLog(
                entity_id=lease.entity_id,
                generation=lease.generation,
                state=lease.state,
                reason=lease.reason,
                event_id=lease.event_id,
                created_at=naive(clock.utcnow()),
            )
        )

    async def start(self):
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            leases = list((await session.scalars(select(MeetingLease).limit(101))).all())
            if len(leases) > 100:
                raise SuggestionError("MEETING_CAPACITY", 503)
            for lease in leases:
                if lease.state in {"applying", "restoring"}:
                    lease.state, lease.reason, lease.updated_at = (
                        "unknown",
                        "CORE_RESTARTED",
                        naive(clock.utcnow()),
                    )
                    self.log(session, lease)
            pending = any(lease.state in {"waiting", "active", "external"} for lease in leases)
        if (self.enabled or pending) and self.task is None:
            self.task = asyncio.create_task(self.loop())

    async def close(self):
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None

    async def loop(self):
        while True:
            try:
                await self.tick()
                self.status = "ready" if self.enabled else "restoring"
                if not self.enabled:
                    async with base.async_session() as session:
                        pending = await session.scalar(
                            select(MeetingLease.entity_id)
                            .where(MeetingLease.state.in_(["waiting", "active", "external"]))
                            .limit(1)
                        )
                    if pending is None:
                        self.status = "disabled"
                        return
            except asyncio.CancelledError:
                raise
            except Exception:
                self.status = "MEETING_ERROR"
            await asyncio.sleep(2)

    async def decide(self, event_id, decision, revision, scope, targets):
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            old = await session.get(MeetingPlan, event_id)
            event = await session.get(CalendarEvent, event_id)
            now = naive(clock.utcnow())
            if decision == "disable":
                if old is not None:
                    old.status, old.updated_at = "disabled", now
                if old is None and (event is None or event.config_key != self.calendar.config_key):
                    raise SuggestionError("CALENDAR_EVENT_NOT_FOUND", 404)
                return
            if event is None or event.config_key != self.calendar.config_key:
                raise SuggestionError("CALENDAR_EVENT_NOT_FOUND", 404)
            meta = await self.calendar.snapshot(session)
            if not self.enabled:
                raise SuggestionError("MEETING_DISABLED", 409)
            if meta["stale"]:
                raise SuggestionError("CALENDAR_STALE", 409)
            if event.revision != revision or self.scope(event) != scope:
                raise SuggestionError("MEETING_SCOPE_CHANGED", 409)
            if not self.eligible(event, now):
                raise SuggestionError("MEETING_NOT_ELIGIBLE", 422)
            if (
                not targets
                or len(set(targets)) != len(targets)
                or any(target not in self.allowed for target in targets)
            ):
                raise SuggestionError("MEETING_TARGET_NOT_ALLOWED", 422)
            total = await session.scalar(select(func.count()).select_from(MeetingPlan))
            if old is None and total >= 200:
                raise SuggestionError("MEETING_CAPACITY", 409)
            started = (
                old.started_json
                if old is not None and old.policy_scope == scope and old.event_revision == revision
                else "[]"
            )
            await session.merge(
                MeetingPlan(
                    event_id=event_id,
                    calendar_scope=self.calendar.config_key,
                    event_revision=revision,
                    policy_scope=scope,
                    targets_json=encode(sorted(targets)),
                    started_json=started,
                    status="approved",
                    starts_at=event.starts_at,
                    ends_at=event.ends_at,
                    updated_at=now,
                )
            )

    async def acknowledge(self, entity, generation):
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            lease = await session.get(MeetingLease, entity)
            if lease is None:
                raise SuggestionError("MEETING_LEASE_NOT_FOUND", 404)
            if lease.generation != generation or lease.state != "unknown":
                raise SuggestionError("MEETING_LEASE_CHANGED", 409)
            lease.state, lease.reason, lease.members_json = "completed", "USER_ACKNOWLEDGED", "[]"
            lease.updated_at = naive(clock.utcnow())
            self.log(session, lease)

    async def desired(self, session, now):
        meta = await self.calendar.snapshot(session)
        plans = list((await session.scalars(select(MeetingPlan).limit(201))).all())
        leases = list((await session.scalars(select(MeetingLease).limit(101))).all())
        if len(plans) > 200 or len(leases) > 100:
            raise SuggestionError("MEETING_CAPACITY", 503)
        current = {}
        for plan in plans:
            event = await session.get(CalendarEvent, plan.event_id)
            if plan.status != "approved":
                continue
            if now >= plan.ends_at:
                plan.status, plan.updated_at = "finished", now
                continue
            if (
                plan.calendar_scope != self.calendar.config_key
                or event is None
                or self.scope(event) != plan.policy_scope
                or not self.eligible(event, now)
            ):
                plan.status, plan.updated_at = "needs_review", now
                continue
            if plan.starts_at <= now < plan.ends_at:
                current[plan.event_id] = plan
        by_entity = {lease.entity_id: lease for lease in leases}
        # Существующее владение переживает временный stale только до сохранённого конца.
        for lease in leases:
            members = [
                identity
                for identity in json.loads(lease.members_json)
                if identity in current
                and lease.entity_id in json.loads(current[identity].targets_json)
                and self.enabled
            ]
            if encode(members) != lease.members_json:
                lease.members_json = encode(members)
                lease.updated_at = now
            if not members and lease.state in {"waiting", "external"}:
                lease.state, lease.reason = "completed", "NO_ACTIVE_MEETING"
                self.log(session, lease)
        if self.enabled and not meta["stale"]:
            for plan in current.values():
                started = set(json.loads(plan.started_json))
                for entity in json.loads(plan.targets_json):
                    lease = by_entity.get(entity)
                    if (
                        entity in started
                        or lease is not None
                        and lease.state in {"unknown", "applying", "restoring"}
                    ):
                        continue
                    if lease is None:
                        if len(by_entity) >= 100:
                            raise SuggestionError("MEETING_CAPACITY", 503)
                        lease = MeetingLease(
                            entity_id=entity,
                            generation=str(uuid4()),
                            state="waiting",
                            members_json="[]",
                            reason="WAITING_START",
                            created_at=now,
                            updated_at=now,
                        )
                        session.add(lease)
                        leases.append(lease)
                        by_entity[entity] = lease
                    elif lease.state == "completed":
                        lease.generation = str(uuid4())
                        lease.state, lease.members_json, lease.reason = (
                            "waiting",
                            "[]",
                            "WAITING_START",
                        )
                        (
                            lease.context_hash,
                            lease.last_changed,
                            lease.last_updated,
                            lease.event_id,
                            lease.retry_at,
                        ) = None, None, None, None, None
                        lease.created_at = now
                    members = set(json.loads(lease.members_json))
                    members.add(plan.event_id)
                    lease.members_json = encode(sorted(members))
                    lease.updated_at = now
                    started.add(entity)
                    self.log(session, lease)
                plan.started_json = encode(sorted(started))
        await session.execute(
            delete(MeetingPlan).where(MeetingPlan.ends_at < now - timedelta(days=7))
        )
        await session.execute(
            delete(MeetingLog).where(MeetingLog.created_at < now - timedelta(days=90))
        )
        newest = select(func.max(MeetingLog.id)).scalar_subquery()
        await session.execute(delete(MeetingLog).where(MeetingLog.id <= newest - 1000))
        return [
            lease.entity_id
            for lease in leases
            if (
                lease.state == "waiting"
                or lease.state == "active"
                and not json.loads(lease.members_json)
            )
            and (lease.retry_at is None or lease.retry_at <= now)
        ]

    async def tick(self):
        async with self.lock:
            async with base.async_session() as session, session.begin():
                await session.connection(execution_options={"sqlite_immediate": True})
                targets = await self.desired(session, naive(clock.utcnow()))
            for entity in targets:
                await self.transition(entity)

    async def write(
        self, entity, generation, state, reason, *, observation=None, event_id=None, retry=False
    ):
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            lease = await session.get(MeetingLease, entity)
            if lease is None or lease.generation != generation:
                return
            old = (lease.state, lease.reason)
            if event_id is not None:
                lease.event_id = event_id
            lease.state, lease.reason, lease.updated_at = (
                state,
                reason,
                naive(clock.utcnow()),
            )
            lease.retry_at = lease.updated_at + timedelta(seconds=30) if retry else None
            if observation is not None:
                lease.context_hash = digest(observation.context.id)
                lease.last_changed, lease.last_updated = (
                    naive(observation.last_changed),
                    naive(observation.last_updated),
                )
            if old != (state, reason):
                self.log(session, lease)

    async def interested(self, session, entity, now):
        if not self.enabled or (await self.calendar.snapshot(session))["stale"]:
            return False
        plans = (
            await session.scalars(
                select(MeetingPlan).where(MeetingPlan.status == "approved").limit(200)
            )
        ).all()
        lease = await session.get(MeetingLease, entity)
        members = set(json.loads(lease.members_json)) if lease else set()
        for plan in plans:
            if plan.event_id not in members and entity in json.loads(plan.started_json):
                continue
            if not plan.starts_at <= now < plan.ends_at or entity not in json.loads(
                plan.targets_json
            ):
                continue
            event = await session.get(CalendarEvent, plan.event_id)
            if self.eligible(event, now) and plan.policy_scope == self.scope(event):
                return True
        return False

    async def transition(self, entity):
        async with base.async_session() as session:
            lease = await session.get(MeetingLease, entity)
            if lease is None:
                return
            generation, state = lease.generation, lease.state
            mode = (
                "start"
                if state == "waiting" and json.loads(lease.members_json)
                else "restore"
                if state == "active" and not json.loads(lease.members_json)
                else None
            )
            if mode is None:
                return
        if entity not in self.allowed:
            await self.write(entity, generation, "unknown", "POLICY_REVOKED")
            return
        try:
            before = await self.client.get_state(entity)
        except HAError:
            await self.write(entity, generation, state, "HA_UNAVAILABLE", retry=True)
            return
        if mode == "start":
            if before.state == "on":
                await self.write(entity, generation, "external", "ALREADY_ON")
                return
            if before.state != "off" or before.context is None:
                await self.write(entity, generation, state, "CONTEXT_REQUIRED", retry=True)
                return
        elif (
            before.state != "on"
            or before.context is None
            or digest(before.context.id) != lease.context_hash
            or naive(before.last_changed) != lease.last_changed
            or naive(before.last_updated) != lease.last_updated
        ):
            await self.write(entity, generation, "completed", "MANUAL_CHANGE_PRESERVED")
            return
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            current = await session.get(MeetingLease, entity)
            wanted = await self.interested(session, entity, naive(clock.utcnow()))
            if current is None or current.generation != generation or current.state != state:
                return
            if mode == "start" and (not wanted or not json.loads(current.members_json)):
                return
            if mode == "restore" and (wanted or json.loads(current.members_json)):
                return
            current.state = "applying" if mode == "start" else "restoring"
            current.event_id = None
            current.reason = "COMMAND_IN_FLIGHT"
            current.updated_at = naive(clock.utcnow())
            self.log(session, current)
        event_id = None
        try:
            async with base.async_session() as session:
                result = await execute_command(
                    session,
                    self.client,
                    "switch",
                    "turn_on" if mode == "start" else "turn_off",
                    entity,
                    {},
                )
            event_id = result["event_id"]
            if mode == "restore":
                await self.write(
                    entity,
                    generation,
                    "completed"
                    if result["state_observed"] and result["new_state"] == "off"
                    else "unknown",
                    "RESTORE_OBSERVED"
                    if result["state_observed"] and result["new_state"] == "off"
                    else "RESTORE_UNCONFIRMED",
                    event_id=event_id,
                )
                return
            changed = [
                HAState.model_validate(raw)
                for raw in result["result"]
                if raw.get("entity_id") == entity
            ]
            after = await self.client.get_state(entity)
            if (
                len(changed) != 1
                or changed[0].state != "on"
                or changed[0].context is None
                or after.state != "on"
                or after.context is None
                or after.context.id == before.context.id
                or changed[0].context.id != after.context.id
                or changed[0].last_changed != after.last_changed
                or changed[0].last_updated != after.last_updated
            ):
                await self.write(
                    entity, generation, "unknown", "OWNERSHIP_UNCONFIRMED", event_id=event_id
                )
                return
            await self.write(
                entity, generation, "active", "MODE_ACTIVE", observation=after, event_id=event_id
            )
        except asyncio.CancelledError:
            raise
        except HTTPException as error:
            data = error.detail if isinstance(error.detail, dict) else {}
            await self.write(
                entity,
                generation,
                "unknown",
                "AUDIT_UNAVAILABLE"
                if data.get("code") == "AUDIT_UNAVAILABLE"
                else "COMMAND_UNCONFIRMED",
                event_id=data.get("event_id"),
            )
        except Exception:
            await self.write(
                entity, generation, "unknown", "COMMAND_UNCONFIRMED", event_id=event_id
            )
