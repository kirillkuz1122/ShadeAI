import asyncio
import json
from contextlib import suppress
from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update

from app.core import clock
from app.db import base
from app.db.models import (
    AutomationRule,
    AutomationRun,
    SensorHistory,
    TelemetryCheckpoint,
    TelemetryGap,
)
from app.services.ha_bridge.audit import execute_command
from app.services.suggestions.service import SuggestionError, action, fingerprint
from app.services.telemetry.store import naive


def in_window(condition: dict, stamp) -> bool:
    local = stamp.replace(tzinfo=UTC).astimezone(ZoneInfo(condition["timezone"]))
    group = "weekdays" if local.weekday() < 5 else "weekends"
    minute = local.hour * 60 + local.minute
    start, end = (
        int(value[:2]) * 60 + int(value[3:])
        for value in (condition["window_start"], condition["window_end"])
    )
    inside = start <= minute <= end if start <= end else minute >= start or minute <= end
    return group == condition["day_group"] and inside


class AutomationExecutor:
    def __init__(self, suggestions, telemetry, client):
        self.suggestions, self.telemetry, self.client = suggestions, telemetry, client
        self.policy = dict(suggestions.execution_scope)
        self.enabled = self.policy["enabled"]
        self.status = "starting" if self.enabled else "disabled"
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.capacity_full = False

    async def start(self):
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            # После аварии неизвестно, дошла ли команда. Никогда не переигрываем.
            for old, new in (("pending", "cancelled"), ("dispatching", "unknown")):
                await session.execute(
                    update(AutomationRun)
                    .where(AutomationRun.state == old)
                    .values(state=new, reason="CORE_RESTARTED", finished_at=naive(clock.utcnow()))
                )
        if self.enabled and self.task is None:
            self.task = asyncio.create_task(self.loop())

    async def stop(self):
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None

    async def loop(self):
        while True:
            try:
                await self.tick()
                self.status = "capacity" if self.capacity_full else "ready"
            except asyncio.CancelledError:
                raise
            except Exception:
                self.status = "EXECUTOR_ERROR"
            await asyncio.sleep(2)

    async def evidence(self, session, rule, now):
        if (
            not self.enabled
            or self.telemetry.status != "connected"
            or self.suggestions.execution_scope != self.policy
        ):
            return None
        home = self.policy["home_presence_entity"]
        primary = self.suggestions.analytics.entity
        if home is None or primary is None or home == primary:
            return None
        checkpoint = await session.get(TelemetryCheckpoint, 1)
        if checkpoint is None or not now - timedelta(seconds=90) <= checkpoint.last_seen <= now:
            return None
        condition = json.loads(rule.trigger_json)
        if condition["entity_id"] != primary:
            return None
        events, previous_at = [], []
        for entity in (primary, home):
            pair = list(
                (
                    await session.scalars(
                        select(SensorHistory)
                        .where(SensorHistory.entity_id == entity)
                        .order_by(SensorHistory.id.desc())
                        .limit(2)
                    )
                ).all()
            )
            if len(pair) != 2:
                return None
            current, previous = pair
            if (
                current.source != "ha_state_changed"
                or previous.source not in {"ha_state_changed", "ha_snapshot"}
                or current.state != condition["to_state"]
                or previous.state != condition["from_state"]
                or not now - timedelta(seconds=300) <= current.observed_at <= now
                or previous.observed_at > current.observed_at
                or current.ha_timestamp is None
                or current.ha_timestamp < previous.observed_at
                or abs((current.ha_timestamp - current.observed_at).total_seconds()) > 120
            ):
                return None
            events.append(current)
            previous_at.append(previous.observed_at)
        if abs((events[0].observed_at - events[1].observed_at).total_seconds()) > 90:
            return None
        if not in_window(condition, events[0].observed_at):
            return None
        gap = await session.scalar(
            select(TelemetryGap.id)
            .where(
                TelemetryGap.started_at <= now,
                (TelemetryGap.ended_at.is_(None)) | (TelemetryGap.ended_at > min(previous_at)),
            )
            .limit(1)
        )
        if gap is not None:
            return None
        return events[0].id, events[1].id

    async def tick(self):
        if not self.enabled:
            return
        async with self.lock:
            async with base.async_session() as session:
                pending = list(
                    (
                        await session.scalars(
                            select(AutomationRun.id)
                            .where(AutomationRun.state == "pending")
                            .order_by(AutomationRun.id)
                            .limit(20)
                        )
                    ).all()
                )
            for identity in pending:
                await self.dispatch(identity)
            async with self.suggestions.lock:
                async with base.async_session() as session, session.begin():
                    await session.connection(execution_options={"sqlite_immediate": True})
                    now = naive(clock.utcnow())
                    _, sources = await self.suggestions.source_context(session)
                    rules = list(
                        (
                            await session.scalars(
                                select(AutomationRule)
                                .where(AutomationRule.status == "accepted")
                                .order_by(AutomationRule.id)
                                .limit(200)
                            )
                        ).all()
                    )
                    count = await session.scalar(
                        select(func.count())
                        .select_from(AutomationRun)
                        .where(AutomationRun.state == "pending")
                    )
                    total = await session.scalar(select(func.count()).select_from(AutomationRun))
                    if total >= 1000:
                        old_ids = (
                            select(AutomationRun.id)
                            .where(
                                AutomationRun.finished_at < now - timedelta(days=1),
                                AutomationRun.state.not_in(["pending", "dispatching"]),
                            )
                            .order_by(AutomationRun.id)
                            .limit(100)
                        )
                        await session.execute(
                            delete(AutomationRun).where(AutomationRun.id.in_(old_ids))
                        )
                        total = await session.scalar(
                            select(func.count()).select_from(AutomationRun)
                        )
                    self.capacity_full = total >= 1000
                    for rule in rules:
                        if (
                            count >= 20
                            or total >= 1000
                            or not self.suggestions.approved(rule, sources)
                        ):
                            continue
                        evidence = await self.evidence(session, rule, now)
                        if evidence is None:
                            continue
                        # Переодобрение/смена цели не превращает прежний переход в новый.
                        identity = fingerprint([rule.id, *evidence])
                        exists = await session.scalar(
                            select(AutomationRun.id).where(AutomationRun.identity == identity)
                        )
                        if exists is not None:
                            continue
                        command = action(rule)
                        session.add(
                            AutomationRun(
                                identity=identity,
                                rule_id=rule.id,
                                approval_key=rule.approval_key,
                                primary_event_id=evidence[0],
                                home_event_id=evidence[1],
                                target_entity=command["entity_id"],
                                service=command["service"],
                                state="pending",
                                reason="WAITING_CANCEL_WINDOW",
                                created_at=now,
                                due_at=now + timedelta(seconds=self.policy["cancel_seconds"]),
                            )
                        )
                        await session.flush()
                        count += 1
                        total += 1
                    await session.execute(
                        delete(AutomationRun).where(
                            AutomationRun.finished_at < now - timedelta(days=90)
                        )
                    )
                    newest = select(func.max(AutomationRun.id)).scalar_subquery()
                    await session.execute(
                        delete(AutomationRun).where(
                            AutomationRun.id <= newest - 1000,
                            AutomationRun.state.not_in(["pending", "dispatching"]),
                            AutomationRun.finished_at < now - timedelta(days=1),
                        )
                    )

    async def dispatch(self, identity):
        async with self.suggestions.lock:
            async with base.async_session() as session, session.begin():
                await session.connection(execution_options={"sqlite_immediate": True})
                now = naive(clock.utcnow())
                run = await session.get(AutomationRun, identity)
                if run is None or run.state != "pending":
                    return
                rule = await session.get(AutomationRule, run.rule_id)
                _, sources = await self.suggestions.source_context(session)
                evidence = await self.evidence(session, rule, now) if rule else None
                reason = None
                if (
                    rule is None
                    or not self.suggestions.approved(rule, sources)
                    or rule.approval_key != run.approval_key
                ):
                    reason = "APPROVAL_CHANGED"
                elif evidence != (run.primary_event_id, run.home_event_id):
                    reason = "PRESENCE_UNCONFIRMED"
                elif (
                    run.target_entity != rule.target_entity
                    or run.service != action(rule)["service"]
                ):
                    reason = "APPROVAL_CHANGED"
                if reason:
                    run.state, run.reason, run.finished_at = "cancelled", reason, now
                    return
                if run.due_at > now:
                    return
                recent = await session.scalar(
                    select(AutomationRun.id)
                    .where(
                        AutomationRun.target_entity == run.target_entity,
                        AutomationRun.started_at
                        >= now - timedelta(seconds=self.policy["cooldown_seconds"]),
                    )
                    .limit(1)
                )
                if recent is not None:
                    run.state, run.reason, run.finished_at = "skipped", "COOLDOWN", now
                    return
                run.state, run.reason, run.started_at = "dispatching", "COMMAND_IN_FLIGHT", now
                target, service = run.target_entity, run.service
        # dispatching зафиксирован до аудита/HTTP. С этого момента отмена не обещает откат HA.
        state, reason, event_id = "succeeded", "HA_ACCEPTED", None
        try:
            async with base.async_session() as session:
                result = await execute_command(session, self.client, "light", service, target, {})
                event_id = result["event_id"]
        except asyncio.CancelledError:
            raise
        except HTTPException as error:
            detail = error.detail if isinstance(error.detail, dict) else {}
            event_id = detail.get("event_id")
            state = "unknown" if detail.get("outcome") in {"unknown", "accepted"} else "failed"
            reason = {
                "AUDIT_UNAVAILABLE": "AUDIT_UNAVAILABLE",
                "AUDIT_FINALIZATION_FAILED": "AUDIT_FINALIZATION_FAILED",
            }.get(detail.get("code"), "HA_UNCONFIRMED" if state == "unknown" else "HA_FAILED")
        except Exception:
            state, reason = "unknown", "COMMAND_UNCONFIRMED"
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            await session.execute(
                update(AutomationRun)
                .where(AutomationRun.id == identity, AutomationRun.state == "dispatching")
                .values(
                    state=state, reason=reason, event_id=event_id, finished_at=naive(clock.utcnow())
                )
            )

    async def cancel(self, identity):
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            run = await session.get(AutomationRun, identity)
            if run is None:
                raise SuggestionError("AUTOMATION_RUN_NOT_FOUND", 404)
            if run.state == "cancelled":
                return
            if run.state != "pending":
                raise SuggestionError("AUTOMATION_RUN_ALREADY_DISPATCHED", 409)
            run.state, run.reason, run.finished_at = (
                "cancelled",
                "USER_CANCELLED",
                naive(clock.utcnow()),
            )
