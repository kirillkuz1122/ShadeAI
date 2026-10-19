from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_api_key
from app.core import clock
from app.db.base import get_session
from app.db.models import LocalHint, LocalHintState, NotificationRaw
from app.services.telemetry.store import iso, naive

router = APIRouter(tags=["hints"], dependencies=[Depends(verify_api_key)])


@router.get("/hints")
async def hints(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    after_id: Annotated[int, Query(ge=0, le=9_223_372_036_854_775_807)] = 0,
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
) -> dict:
    service = request.app.state.suggestions
    filters = [
        LocalHint.config_key == service.analytics.config_key,
        LocalHint.created_at >= naive(clock.utcnow()) - timedelta(days=7),
    ]
    async with session.begin():
        identity = await session.get(LocalHintState, 1)
        latest = await session.scalar(select(func.max(LocalHint.id)).where(*filters)) or 0
        rows = list(
            (
                await session.scalars(
                    select(LocalHint)
                    .join(NotificationRaw, LocalHint.notification_id == NotificationRaw.id)
                    .where(*filters, LocalHint.id > after_id)
                    .order_by(LocalHint.id)
                    .limit(limit)
                )
            ).all()
        )
    return {
        "feed_id": identity.feed_id if identity else None,
        "latest_id": latest,
        "next_id": rows[-1].id if rows else after_id,
        "hints": [
            {
                "id": row.id,
                "kind": row.kind,
                "notification_id": row.notification_id,
                "created_at": iso(row.created_at),
            }
            for row in rows
        ],
    }
