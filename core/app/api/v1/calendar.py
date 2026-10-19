from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_api_key
from app.db.base import get_session
from app.db.models import CalendarEvent
from app.services.calendar.codec import CalendarError
from app.services.calendar.reminders import schedule, valid_reminder
from app.services.telemetry.store import iso

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
    return await service.snapshot(session)


@router.get("/reminders")
async def reminders(request: Request, session: Session):
    async with session.begin():
        page = await schedule(request.app.state.calendar, session)
    # Никогда не выдаём усечённую выборку как полное расписание.
    if page["overflow"]:
        page["reminders"] = []
    return page


@router.get("/reminders/{reminder_id}")
async def reminder(
    reminder_id: Annotated[str, Path(pattern=r"^rmd_[0-9a-f]{32}$")],
    request: Request,
    session: Session,
):
    async with session.begin():
        page = await schedule(request.app.state.calendar, session)
    if not page["enabled"]:
        raise HTTPException(404, {"code": "CALENDAR_REMINDER_NOT_FOUND"})
    if page["stale"]:
        raise HTTPException(503, {"code": "CALENDAR_STALE"})
    item = valid_reminder(page, reminder_id)
    if item is None:
        raise HTTPException(404, {"code": "CALENDAR_REMINDER_NOT_FOUND"})
    return {key: value for key, value in page.items() if key not in {"reminders", "overflow"}} | {
        "reminder": item
    }


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
