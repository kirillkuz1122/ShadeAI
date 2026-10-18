import json
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_api_key
from app.core import clock
from app.core.config import settings
from app.db.base import get_session
from app.db.models import DeviceState, SensorHistory, TelemetryCheckpoint, TelemetryGap
from app.services.ha_bridge.models import EntityId
from app.services.telemetry.store import iso, naive

router = APIRouter(prefix="/telemetry", tags=["telemetry"], dependencies=[Depends(verify_api_key)])
Session = Annotated[AsyncSession, Depends(get_session)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=500_000)]


def cutoff():
    return naive(clock.utcnow() - timedelta(days=settings.sensor_retention_days))


@router.get("")
async def status(request: Request, session: Session) -> dict:
    collector = request.app.state.telemetry
    status_before, generation_before = collector.status, collector.generation
    async with session.begin():
        checkpoint = await session.get(TelemetryCheckpoint, 1)
        rows = (
            await session.scalars(
                select(DeviceState).where(DeviceState.entity_id.in_(collector.entities))
            )
        ).all()
    cached = {row.entity_id: row for row in rows}
    stale = (
        collector.status != "connected"
        or status_before != "connected"
        or collector.generation != generation_before
    )
    return {
        "status": collector.status,
        "error_code": collector.error,
        "last_confirmed_at": iso(checkpoint.last_seen) if checkpoint else None,
        "retention_days": settings.sensor_retention_days,
        "max_rows": settings.sensor_history_max_rows,
        "states": [
            {
                "entity_id": entity,
                "present": entity in cached,
                "state": cached[entity].state if entity in cached else None,
                "attributes": json.loads(cached[entity].attributes_json)
                if entity in cached
                else {},
                "last_changed": iso(cached[entity].last_changed) if entity in cached else None,
                "last_updated": iso(cached[entity].last_updated) if entity in cached else None,
                "stale": stale,
            }
            for entity in collector.entities
        ],
    }


@router.get("/history")
async def history(
    session: Session,
    entity_id: Annotated[EntityId | None, Query()] = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> dict:
    filters = [
        SensorHistory.entity_id.in_(settings.ha_telemetry_entities),
        SensorHistory.observed_at >= cutoff(),
    ]
    if entity_id is not None:
        filters.append(SensorHistory.entity_id == entity_id)
    async with session.begin():
        total = await session.scalar(
            select(func.count()).select_from(SensorHistory).where(*filters)
        )
        rows = (
            await session.scalars(
                select(SensorHistory)
                .where(*filters)
                .order_by(SensorHistory.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    return {
        "items": [
            {
                "id": row.id,
                "entity_id": row.entity_id,
                "state": row.state,
                "attributes": json.loads(row.attributes_json),
                "source": row.source,
                "ha_timestamp": iso(row.ha_timestamp),
                "observed_at": iso(row.observed_at),
            }
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/gaps")
async def gaps(session: Session, limit: Limit = 50, offset: Offset = 0) -> dict:
    filters = [(TelemetryGap.ended_at.is_(None)) | (TelemetryGap.ended_at >= cutoff())]
    async with session.begin():
        total = await session.scalar(select(func.count()).select_from(TelemetryGap).where(*filters))
        rows = (
            await session.scalars(
                select(TelemetryGap)
                .where(*filters)
                .order_by(TelemetryGap.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    return {
        "items": [
            {
                "id": row.id,
                "started_at": iso(row.started_at),
                "ended_at": iso(row.ended_at),
                "reason": row.reason,
            }
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
