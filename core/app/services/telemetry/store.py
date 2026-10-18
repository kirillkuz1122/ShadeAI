import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from app.core import clock
from app.core.config import settings
from app.db import base
from app.db.models import DeviceState, SensorHistory, TelemetryCheckpoint, TelemetryGap
from app.services.ha_bridge.models import HAState


def naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def iso(value: datetime | None) -> str | None:
    return clock.iso_utc(value.replace(tzinfo=UTC)) if value else None


def attributes(state: HAState) -> str:
    # Не сохраняем friendly_name, context, old_state и произвольные атрибуты HA.
    return json.dumps(
        {
            key: value
            for key in ("unit_of_measurement", "device_class", "state_class")
            if isinstance(value := state.attributes.get(key), str)
            and len(value) <= 64
            and all(ord(char) >= 32 for char in value)
        },
        ensure_ascii=False,
        sort_keys=True,
    )


class TelemetryStore:
    def __init__(self, entities: tuple[str, ...]):
        self.entities = entities

    async def prune(self, session) -> None:
        cutoff = naive(clock.utcnow() - timedelta(days=settings.sensor_retention_days))
        await session.execute(
            delete(SensorHistory).where(
                (SensorHistory.observed_at < cutoff) | SensorHistory.entity_id.not_in(self.entities)
            )
        )
        newest = select(func.max(SensorHistory.id)).scalar_subquery()
        await session.execute(
            delete(SensorHistory).where(
                SensorHistory.id <= newest - settings.sensor_history_max_rows
            )
        )
        await session.execute(
            delete(DeviceState).where(DeviceState.entity_id.not_in(self.entities))
        )
        await session.execute(delete(TelemetryGap).where(TelemetryGap.ended_at < cutoff))
        newest_gap = select(func.max(TelemetryGap.id)).scalar_subquery()
        await session.execute(delete(TelemetryGap).where(TelemetryGap.id <= newest_gap - 1000))

    async def gap(self, reason: str) -> None:
        async with base.async_session() as session, session.begin():
            opened = await session.scalar(
                select(TelemetryGap).where(TelemetryGap.ended_at.is_(None))
            )
            if opened is None:
                checkpoint = await session.get(TelemetryCheckpoint, 1)
                session.add(
                    TelemetryGap(
                        started_at=checkpoint.last_seen if checkpoint else naive(clock.utcnow()),
                        reason=reason,
                    )
                )
            await session.flush()
            await self.prune(session)

    async def checkpoint(self) -> None:
        async with base.async_session() as session, session.begin():
            await session.merge(TelemetryCheckpoint(id=1, last_seen=naive(clock.utcnow())))
            await self.prune(session)

    async def write(
        self,
        states: dict[str, HAState | None],
        *,
        snapshot: bool = False,
        event_at: datetime | None = None,
    ) -> None:
        now = naive(clock.utcnow())
        async with base.async_session() as session, session.begin():
            for entity, state in states.items():
                if entity not in self.entities:
                    continue
                attrs = attributes(state) if state else "{}"
                if state:
                    await session.merge(
                        DeviceState(
                            entity_id=entity,
                            state=state.state,
                            attributes_json=attrs,
                            last_changed=naive(state.last_changed),
                            last_updated=naive(state.last_updated),
                        )
                    )
                else:
                    await session.execute(
                        delete(DeviceState).where(DeviceState.entity_id == entity)
                    )
                session.add(
                    SensorHistory(
                        entity_id=entity,
                        state=state.state if state else None,
                        attributes_json=attrs,
                        source="ha_snapshot" if snapshot else "ha_state_changed",
                        ha_timestamp=naive(event_at) if event_at else None,
                        observed_at=now,
                    )
                )
            if snapshot:
                gaps = (
                    await session.scalars(
                        select(TelemetryGap).where(TelemetryGap.ended_at.is_(None))
                    )
                ).all()
                for gap in gaps:
                    gap.ended_at = max(now, gap.started_at)
                await session.merge(TelemetryCheckpoint(id=1, last_seen=now))
            await session.flush()
            await self.prune(session)
