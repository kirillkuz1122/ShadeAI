import asyncio
import hashlib
import json
from contextlib import suppress
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import delete, func, select

from app.core import clock
from app.core.config import settings
from app.db import base
from app.db.models import (
    AnalyticsState,
    AutomationDecision,
    AutomationRule,
    HabitProfile,
    LocalHint,
    LocalHintState,
    NotificationRaw,
    SensorHistory,
    TelemetryCheckpoint,
    TelemetryGap,
)
from app.services.notification.extraction import ExtractedNotification
from app.services.telemetry.store import naive


class SuggestionError(Exception):
    def __init__(self, code: str, status: int):
        self.code, self.status = code, status
        super().__init__(code)


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


def trigger(profile: HabitProfile) -> dict:
    data = json.loads(profile.profile_json)
    return {
        "type": "presence_transition",
        "entity_id": profile.entity_id,
        "from_state": "off" if profile.kind == "arrival_home" else "on",
        "to_state": "on" if profile.kind == "arrival_home" else "off",
        "kind": profile.kind,
        "day_group": profile.day_group,
        "timezone": profile.timezone,
        **{key: data[key] for key in ("window_start", "window_end", "wraps_midnight")},
    }


def action(rule: AutomationRule) -> dict | None:
    if rule.target_entity is None:
        return None
    return {
        "entity_id": rule.target_entity,
        "service": "turn_on"
        if json.loads(rule.trigger_json)["kind"] == "arrival_home"
        else "turn_off",
        "params": {},
    }


class SuggestionService:
    def __init__(self, analytics, telemetry):
        self.analytics, self.telemetry = analytics, telemetry
        self.allowed = tuple(settings.automation_allowed_lights)
        self.interval = settings.suggestions_interval_seconds
        self.status = "starting"
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()

    def approval_key(self, profile_key: str, target: str | None) -> str:
        return fingerprint([1, profile_key, target, sorted(self.allowed)])

    async def start(self) -> None:
        if self.task is not None:
            return
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            if await session.get(LocalHintState, 1) is None:
                session.add(LocalHintState(id=1, feed_id=str(uuid4())))
        try:
            await self.refresh()
        except Exception:
            self.status = "SUGGESTIONS_ERROR"
        if self.analytics.entity is not None:
            self.task = asyncio.create_task(self.loop())

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None

    async def loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.status = "SUGGESTIONS_ERROR"

    async def source_context(self, session):
        snapshot = await session.get(AnalyticsState, 1)
        known = (
            self.analytics.entity is not None
            and snapshot is not None
            and snapshot.config_key == self.analytics.config_key
            and self.analytics.status not in {"starting", "calculating", "ANALYTICS_ERROR"}
            and snapshot.computed_at
            >= naive(clock.utcnow()) - timedelta(seconds=self.analytics.interval * 2)
        )
        profiles = (
            list(
                (
                    await session.scalars(
                        select(HabitProfile)
                        .where(HabitProfile.config_key == self.analytics.config_key)
                        .limit(4)
                    )
                ).all()
            )
            if known
            else []
        )
        current = {
            row.id: row for row in profiles if json.loads(row.profile_json)["confidence"] >= 0.75
        }
        return known, current

    def valid(self, rule: AutomationRule, sources) -> bool:
        source = sources.get(rule.source_habit_id)
        return (
            source is not None
            and rule.config_key == self.analytics.config_key
            and fingerprint(trigger(source)) == rule.profile_key
        )

    def approved(self, rule: AutomationRule, sources) -> bool:
        return (
            rule.status == "accepted"
            and self.valid(rule, sources)
            and rule.target_entity in self.allowed
            and rule.approval_key == self.approval_key(rule.profile_key, rule.target_entity)
        )

    def history(self, session, rule, decision, now):
        session.add(
            AutomationDecision(
                rule_id=rule.id,
                decision=decision,
                version=rule.version,
                target_entity=rule.target_entity,
                created_at=now,
            )
        )

    async def refresh(self) -> None:
        async with self.lock:
            now = naive(clock.utcnow())
            async with base.async_session() as session, session.begin():
                # Writer резервируется до чтения, иначе возможен SQLITE_BUSY_SNAPSHOT.
                await session.connection(execution_options={"sqlite_immediate": True})
                known, sources = await self.source_context(session)
                rules = list(
                    (
                        await session.scalars(
                            select(AutomationRule).order_by(AutomationRule.id).limit(201)
                        )
                    ).all()
                )
                existing = {row.source_habit_id: row for row in rules}
                for source in sources.values():
                    data = json.loads(source.profile_json)
                    condition = trigger(source)
                    key = fingerprint(condition)
                    evidence = {
                        name: data[name]
                        for name in ("support_days", "eligible_days", "dispersion_minutes")
                    }
                    rule = existing.get(source.id)
                    if rule is None and len(existing) < 200:
                        rule = AutomationRule(
                            id="aut_" + fingerprint(source.id)[:32],
                            source_habit_id=source.id,
                            profile_key=key,
                            config_key=self.analytics.config_key,
                            trigger_json=encode(condition),
                            evidence_json=encode(evidence),
                            confidence=data["confidence"],
                            status="pending",
                            source_stale=0,
                            version=1,
                            created_at=now,
                            updated_at=now,
                        )
                        session.add(rule)
                        existing[source.id] = rule
                        self.history(session, rule, "suggested", now)
                    elif rule is not None:
                        changed = (
                            rule.profile_key != key or rule.config_key != self.analytics.config_key
                        )
                        updated = (
                            changed
                            or rule.evidence_json != encode(evidence)
                            or rule.confidence != data["confidence"]
                            or rule.source_stale != 0
                        )
                        if changed and rule.status == "accepted":
                            rule.status, rule.approval_key = "needs_review", None
                        if updated:
                            rule.profile_key, rule.config_key = key, self.analytics.config_key
                            rule.trigger_json, rule.evidence_json = (
                                encode(condition),
                                encode(evidence),
                            )
                            rule.confidence, rule.source_stale = data["confidence"], 0
                            rule.version += 1
                            rule.updated_at = now
                            self.history(
                                session,
                                rule,
                                "source_changed" if changed else "evidence_updated",
                                now,
                            )
                for rule in existing.values():
                    stale = not self.valid(rule, sources)
                    policy_changed = (
                        rule.status == "accepted"
                        and rule.approval_key
                        != self.approval_key(rule.profile_key, rule.target_entity)
                    )
                    invalidate = (
                        known and stale or self.analytics.entity is None or policy_changed
                    ) and rule.status == "accepted"
                    if int(stale) != rule.source_stale or invalidate:
                        rule.source_stale = int(stale)
                        if invalidate:
                            rule.status, rule.approval_key = "needs_review", None
                        rule.version += 1
                        rule.updated_at = now
                        self.history(
                            session,
                            rule,
                            "approval_invalidated" if invalidate else "source_unavailable",
                            now,
                        )
                await self.make_hint(session, now)
                await session.execute(
                    delete(LocalHint).where(LocalHint.created_at < now - timedelta(days=7))
                )
                newest = select(func.max(LocalHint.id)).scalar_subquery()
                await session.execute(delete(LocalHint).where(LocalHint.id <= newest - 1000))
                newest_decision = select(func.max(AutomationDecision.id)).scalar_subquery()
                await session.execute(
                    delete(AutomationDecision).where(
                        (AutomationDecision.id <= newest_decision - 1000)
                        | (AutomationDecision.created_at < now - timedelta(days=90))
                    )
                )
            self.status = "disabled" if self.analytics.entity is None else "ready"

    async def make_hint(self, session, now) -> None:
        if self.analytics.entity is None or self.telemetry.status != "connected":
            return
        checkpoint = await session.get(TelemetryCheckpoint, 1)
        if checkpoint is None or not now - timedelta(
            seconds=90
        ) <= checkpoint.last_seen <= now + timedelta(seconds=5):
            return
        rows = list(
            (
                await session.scalars(
                    select(SensorHistory)
                    .where(SensorHistory.entity_id == self.analytics.entity)
                    .order_by(SensorHistory.id.desc())
                    .limit(2)
                )
            ).all()
        )
        if len(rows) != 2:
            return
        current, previous = rows
        if (
            current.source != "ha_state_changed"
            or current.state != "on"
            or previous.state != "off"
            or previous.source not in {"ha_state_changed", "ha_snapshot"}
            or not now - timedelta(minutes=5) <= current.observed_at <= now
            or current.observed_at < previous.observed_at
            or current.ha_timestamp is None
            or current.ha_timestamp < previous.observed_at
            or abs((current.ha_timestamp - current.observed_at).total_seconds()) > 120
        ):
            return
        gap = await session.scalar(
            select(TelemetryGap.id)
            .where(
                TelemetryGap.started_at <= now,
                (TelemetryGap.ended_at.is_(None)) | (TelemetryGap.ended_at > previous.observed_at),
            )
            .limit(1)
        )
        if (
            gap is not None
            or await session.scalar(
                select(LocalHint.id).where(LocalHint.presence_event_id == current.id)
            )
            is not None
        ):
            return
        recent = await session.scalar(
            select(LocalHint.id)
            .where(
                LocalHint.config_key == self.analytics.config_key,
                LocalHint.kind == "arrival_delivery",
                LocalHint.created_at >= now - timedelta(hours=1),
            )
            .limit(1)
        )
        if recent is not None:
            return
        used = select(LocalHint.notification_id).where(
            LocalHint.config_key == self.analytics.config_key,
            LocalHint.created_at >= now - timedelta(days=1),
        )
        candidates = list(
            (
                await session.scalars(
                    select(NotificationRaw)
                    .where(
                        NotificationRaw.processing_status == "processed",
                        NotificationRaw.payload_hash.is_not(None),
                        NotificationRaw.dedupe_key.is_not(None),
                        NotificationRaw.id.not_in(used),
                        NotificationRaw.app_name.in_(settings.notification_allowed_apps),
                        NotificationRaw.category == "delivery",
                        NotificationRaw.created_at >= now - timedelta(days=1),
                    )
                    .order_by(NotificationRaw.id.desc())
                    .limit(100)
                )
            ).all()
        )
        for notification in candidates:
            try:
                result = ExtractedNotification.model_validate_json(
                    notification.extracted_data_json or ""
                )
            except ValueError:
                continue
            if result.category == "delivery":
                session.add(
                    LocalHint(
                        config_key=self.analytics.config_key,
                        presence_event_id=current.id,
                        notification_id=notification.id,
                        kind="arrival_delivery",
                        created_at=now,
                    )
                )
                return

    async def decide(self, rule_id: str, decision: str, version: int, target: str | None):
        async with self.lock:
            async with base.async_session() as session, session.begin():
                # Writer резервируется до чтения, иначе возможен SQLITE_BUSY_SNAPSHOT.
                await session.connection(execution_options={"sqlite_immediate": True})
                rule = await session.get(AutomationRule, rule_id)
                if rule is None:
                    raise SuggestionError("AUTOMATION_NOT_FOUND", 404)
                if decision != "disable" and version != rule.version:
                    raise SuggestionError("AUTOMATION_CHANGED", 409)
                _, sources = await self.source_context(session)
                if decision == "accept":
                    if not self.valid(rule, sources):
                        raise SuggestionError("AUTOMATION_SOURCE_STALE", 409)
                    if target not in self.allowed:
                        raise SuggestionError("AUTOMATION_TARGET_NOT_ALLOWED", 422)
                    rule.status, rule.target_entity = "accepted", target
                    rule.approval_key = self.approval_key(rule.profile_key, target)
                    rule.source_stale = 0
                else:
                    rule.status = "disabled" if decision == "disable" else "rejected"
                    rule.approval_key = None
                rule.version += 1
                rule.updated_at = naive(clock.utcnow())
                self.history(session, rule, decision, rule.updated_at)
            return rule
