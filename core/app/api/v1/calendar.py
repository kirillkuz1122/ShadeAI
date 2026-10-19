from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_api_key
from app.core import clock
from app.db.base import get_session
from app.db.models import CalendarEvent, CalendarSyncState
from app.services.calendar.codec import CalendarError
from app.services.telemetry.store import iso, naive

router = APIRouter(prefix="/calendar", tags=["calendar"], dependencies=[Depends(verify_api_key)])
Session = Annotated[AsyncSession, Depends(get_session)]


def payload(row):
    return dict(
        id=row.id,
        summary=row.summary,
        location=row.location,
        starts_at=iso(row.starts_at),
        ends_at=iso(row.ends_at),
        start_date=row.start_date,
        end_date=row.end_date,
        all_day=row.start_date is not None,
        status=row.status,
        busy=bool(row.busy),
        revision=row.revision,
        updated_at=iso(row.updated_at),
    )


async def metadata(service, session):
    state = await session.get(CalendarSyncState, 1)
    valid = state is not None and state.config_key == service.config_key
    success = state.last_success if valid else None
    now = naive(clock.utcnow())
    stale = (
        success is None
        or service.status != "ready"
        or not now - timedelta(seconds=service.interval * 2)
        <= success
        <= now + timedelta(seconds=5)
    )
    return dict(
        status=service.status,
        configured=service.url is not None,
        stale=stale,
        timezone=service.timezone,
        last_success=iso(success),
        window_start=iso(state.window_start) if valid else None,
        window_end=iso(state.window_end) if valid else None,
        error_code=state.error_code if valid else None,
    )


@router.get("/events")
async def events(
    request: Request,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    offset: Annotated[int, Query(ge=0, le=1000)] = 0,
    include_inactive: bool = False,
):
    service = request.app.state.calendar
    filters = [CalendarEvent.config_key == service.config_key]
    if not include_inactive:
        filters.append(CalendarEvent.status.in_(["confirmed", "tentative"]))
    async with session.begin():
        meta = await metadata(service, session)
        total = await session.scalar(
            select(func.count()).select_from(CalendarEvent).where(*filters)
        )
        rows = list(
            (
                await session.scalars(
                    select(CalendarEvent)
                    .where(*filters)
                    .order_by(CalendarEvent.starts_at, CalendarEvent.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
    return {**meta, "events": [payload(row) for row in rows], "total": total}


@router.get("/events/{event_id}")
async def detail(
    event_id: Annotated[str, Path(pattern=r"^cal_[0-9a-f]{32}$")],
    request: Request,
    session: Session,
):
    service = request.app.state.calendar
    async with session.begin():
        row = await session.get(CalendarEvent, event_id)
        if row is None or row.config_key != service.config_key:
            raise HTTPException(404, {"code": "CALENDAR_EVENT_NOT_FOUND"})
        meta = await metadata(service, session)
    return {**meta, "event": payload(row)}


@router.post("/sync")
async def sync(request: Request):
    service = request.app.state.calendar
    try:
        await service.sync()
    except CalendarError as error:
        raise HTTPException(503, {"code": error.code}) from None
    return {"status": service.status}
