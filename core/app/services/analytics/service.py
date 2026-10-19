import asyncio
import hashlib
import json
from contextlib import suppress
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from app.core import clock
from app.core.config import settings
from app.db import base
from app.db.models import (
    AnalyticsState,
    HabitProfile,
    SensorHistory,
    TelemetryCheckpoint,
    TelemetryGap,
)
from app.services.analytics.engine import MAX_OBSERVATIONS, Gap, Observation, analyze
from app.services.telemetry.store import naive


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC)


class AnalyticsService:
    def __init__(self):
        self.entity = settings.analytics_presence_entity
        self.timezone = settings.analytics_timezone
        self.interval = settings.analytics_interval_seconds
        self.config_key = hashlib.sha256(
            json.dumps([1, self.entity, self.timezone], ensure_ascii=True).encode()
        ).hexdigest()
        self.status = "disabled" if self.entity is None else "starting"
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()

    async def start(self) -> None:
        if self.task is not None:
            return
        if self.entity is None:
            async with base.async_session() as session, session.begin():
                await session.execute(delete(HabitProfile))
                await session.execute(delete(AnalyticsState))
            return
        self.task = asyncio.create_task(self.loop())

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None

    async def loop(self) -> None:
        while True:
            try:
                await self.recompute()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.status = "ANALYTICS_ERROR"
            await asyncio.sleep(self.interval)

    async def recompute(self) -> None:
        if self.entity is None:
            return
        async with self.lock:
            self.status = "calculating"
            now = clock.utcnow()
            zone = ZoneInfo(self.timezone)
            start = datetime.combine(
                now.astimezone(zone).date() - timedelta(days=30), time.min, zone
            )
            start_naive = naive(start)
            async with base.async_session() as session, session.begin():
                rows = list(
                    (
                        await session.scalars(
                            select(SensorHistory)
                            .where(
                                SensorHistory.entity_id == self.entity,
                                SensorHistory.observed_at >= start_naive,
                            )
                            .order_by(SensorHistory.observed_at, SensorHistory.id)
                            .limit(MAX_OBSERVATIONS + 1)
                        )
                    ).all()
                )
                previous = await session.scalar(
                    select(SensorHistory)
                    .where(
                        SensorHistory.entity_id == self.entity,
                        SensorHistory.observed_at < start_naive,
                    )
                    .order_by(SensorHistory.observed_at.desc(), SensorHistory.id.desc())
                    .limit(1)
                )
                if previous is not None:
                    rows.insert(0, previous)
                checkpoint = await session.get(TelemetryCheckpoint, 1)
                gap_rows = list(
                    (
                        await session.scalars(
                            select(TelemetryGap).order_by(TelemetryGap.id).limit(1001)
                        )
                    ).all()
                )
                observations = [
                    Observation(
                        aware(row.observed_at),
                        row.state,
                        row.source,
                        aware(row.ha_timestamp) if row.ha_timestamp else None,
                    )
                    for row in rows
                ]
                gaps = [
                    Gap(aware(row.started_at), aware(row.ended_at) if row.ended_at else None)
                    for row in gap_rows
                ]
                if gap_rows and gap_rows[0].id > 1 and gap_rows[0].started_at > start_naive:
                    gaps.insert(0, Gap(start.astimezone(UTC), aware(gap_rows[0].started_at)))
                confirmed = aware(checkpoint.last_seen) if checkpoint else None
            report = await asyncio.to_thread(
                analyze, observations, gaps, confirmed, now=now, timezone=self.timezone
            )
            stored = naive(now)
            async with base.async_session() as session, session.begin():
                await session.connection(execution_options={"sqlite_immediate": True})
                ids = []
                for profile in report["profiles"]:
                    identity = json.dumps(
                        [self.entity, self.timezone, profile["kind"], profile["day_group"]]
                    )
                    profile_id = "hbt_" + hashlib.sha256(identity.encode()).hexdigest()[:32]
                    ids.append(profile_id)
                    await session.merge(
                        HabitProfile(
                            id=profile_id,
                            entity_id=self.entity,
                            timezone=self.timezone,
                            kind=profile["kind"],
                            day_group=profile["day_group"],
                            config_key=self.config_key,
                            profile_json=json.dumps(profile),
                            updated_at=stored,
                        )
                    )
                await session.execute(delete(HabitProfile).where(HabitProfile.id.not_in(ids)))
                await session.merge(
                    AnalyticsState(
                        id=1,
                        config_key=self.config_key,
                        snapshot_json=json.dumps(
                            {key: value for key, value in report.items() if key != "profiles"}
                        ),
                        computed_at=stored,
                    )
                )
            self.status = report["status"]
