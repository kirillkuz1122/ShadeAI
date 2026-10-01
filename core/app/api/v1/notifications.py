import json

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import verify_api_key
from app.db.base import get_session
from app.db.models import NotificationRaw
from app.events.bus import bus
from app.schemas import NotificationIn
from app.services.notification.processor import process_notification

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
    dependencies=[Depends(verify_api_key)],
)


@router.post("", status_code=201)
async def ingest(notification: NotificationIn, session=Depends(get_session)) -> dict:
    row = NotificationRaw(**notification.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)

    await bus.publish("notification_received", {"id": row.id, **notification.model_dump()})

    processed = await process_notification(notification.model_dump())
    return {"id": row.id, "status": "queued", "processed_data": processed}


@router.get("")
async def list_notifications(
    limit: int = 50, offset: int = 0, session=Depends(get_session)
) -> dict:
    rows = (await session.scalars(
        select(NotificationRaw).order_by(NotificationRaw.id.desc()).limit(limit).offset(offset)
    )).all()
    return {
        "items": [
            {
                "id": r.id,
                "app_name": r.app_name,
                "title": r.title,
                "text": r.text,
                "timestamp": r.timestamp,
                "priority": r.priority,
                "category": r.category,
                "processed_data": (
                    json.loads(r.extracted_data_json) if r.extracted_data_json else None
                ),
            }
            for r in rows
        ],
        "total": len(rows),
    }
