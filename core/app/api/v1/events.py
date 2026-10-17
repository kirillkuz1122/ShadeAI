import re
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_api_key
from app.core import clock
from app.db.base import get_session
from app.db.models import EventLog
from app.services.ha_bridge.audit import COMMAND_EVENTS, event_cutoff, safe_payload

router = APIRouter(prefix="/events", tags=["events"], dependencies=[Depends(verify_api_key)])


def parse_bound(value: str | None, end: bool) -> datetime | None:
    if value is None:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            parsed = datetime.combine(date.fromisoformat(value), datetime.min.time(), UTC)
            return parsed + timedelta(days=1) if end else parsed
        parsed = TypeAdapter(AwareDatetime).validate_python(value)
        if "T" not in value:
            raise ValueError
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        raise HTTPException(422, "Нужна дата YYYY-MM-DD или ISO 8601 с часовым поясом") from None


@router.get("")
async def events(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    start: Annotated[str | None, Query(alias="from", max_length=40)] = None,
    end: Annotated[str | None, Query(alias="to", max_length=40)] = None,
    event_type: Annotated[str | None, Query(alias="type", max_length=64)] = None,
):
    since, until = parse_bound(start, False), parse_bound(end, True)
    if since and until and since >= until:
        raise HTTPException(422, "Пустой или обратный диапазон времени")
    if event_type is not None and event_type not in COMMAND_EVENTS:
        raise HTTPException(422, "Неизвестный тип события")
    condition = (
        (EventLog.source == "home_assistant")
        & EventLog.event_type.in_(COMMAND_EVENTS)
        & (EventLog.timestamp >= event_cutoff())
    )
    if since:
        condition &= EventLog.timestamp >= since
    if until:
        condition &= EventLog.timestamp < until
    if event_type:
        condition &= EventLog.event_type == event_type
    total = await session.scalar(select(func.count()).select_from(EventLog).where(condition))
    rows = await session.scalars(
        select(EventLog).where(condition).order_by(EventLog.id.desc()).limit(limit).offset(offset)
    )
    return {
        "events": [
            {
                "id": row.id,
                "timestamp": clock.iso_utc(row.timestamp.replace(tzinfo=UTC)),
                "source": row.source,
                "type": row.event_type,
                "payload": safe_payload(row.payload_json),
            }
            for row in rows
        ],
        "total": total,
    }
