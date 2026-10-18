import json
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_api_key
from app.core import clock
from app.db.base import get_session
from app.db.models import AnalyticsState, HabitProfile
from app.services.telemetry.store import iso, naive

router = APIRouter(tags=["analytics"], dependencies=[Depends(verify_api_key)])


@router.get("/habits")
async def habits(request: Request, session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    service = request.app.state.analytics
    async with session.begin():
        snapshot = await session.get(AnalyticsState, 1)
        rows = list(
            (
                await session.scalars(
                    select(HabitProfile)
                    .where(HabitProfile.config_key == service.config_key)
                    .order_by(HabitProfile.id)
                    .limit(4)
                )
            ).all()
        )
    valid = snapshot is not None and snapshot.config_key == service.config_key
    stale = not valid or service.status in {"starting", "calculating", "ANALYTICS_ERROR"}
    if valid:
        stale = stale or snapshot.computed_at < naive(clock.utcnow()) - timedelta(
            seconds=service.interval * 2
        )
    metadata = {
        "status": service.status,
        "entity_id": service.entity,
        "timezone": service.timezone,
        "computed_at": iso(snapshot.computed_at) if valid else None,
        "stale": stale,
        "telemetry_stale": request.app.state.telemetry.status != "connected",
        "score_kind": "heuristic_regularity_not_probability",
        "action_authorized": False,
    }
    result = []
    if valid and service.entity is not None:
        try:
            metadata.update(json.loads(snapshot.snapshot_json))
            # Текущий runtime/error/stale важнее старого сохранённого статуса.
            metadata["status"] = service.status
            for row in rows:
                data = json.loads(row.profile_json)
                group = "будням" if row.day_group == "weekdays" else "выходным"
                kind = "Приход домой" if row.kind == "arrival_home" else "Уход из дома"
                result.append(
                    {
                        "id": row.id,
                        "description": (
                            f"{kind} по {group}, {data['window_start']}–{data['window_end']}"
                        ),
                        "confidence": data["confidence"],
                        "last_seen": data["last_seen"],
                        "pattern": {
                            "kind": row.kind,
                            "day_group": row.day_group,
                            "trigger": row.entity_id,
                            "timezone": row.timezone,
                            "window_start": data["window_start"],
                            "window_end": data["window_end"],
                            "wraps_midnight": data["wraps_midnight"],
                            "radius_minutes": data["radius_minutes"],
                        },
                        "evidence": {
                            key: data[key]
                            for key in ("support_days", "eligible_days", "dispersion_minutes")
                        },
                    }
                )
        except (ValueError, KeyError, TypeError):
            metadata.update(status="ANALYTICS_INVALID_SNAPSHOT", stale=True)
            result = []
    return {"habits": result, "analytics": metadata}
