from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_api_key
from app.core import clock
from app.db.base import get_session
from app.db.models import NotificationRaw
from app.schemas import NotificationIn, NotificationOut, NotificationPage, NotificationReceipt
from app.services.notification.privacy import can_store
from app.services.notification.store import (
    IdentityConflict,
    cutoff,
    save_notification,
    serialize,
    visible_since,
)

router = APIRouter(
    prefix="/notifications", tags=["notifications"], dependencies=[Depends(verify_api_key)]
)
Session = Annotated[AsyncSession, Depends(get_session)]


@router.post(
    "",
    response_model=NotificationReceipt,
    status_code=201,
    responses={
        200: {"model": NotificationReceipt, "description": "Повтор или пропуск по политике"},
        409: {"description": "event_id уже связан с другим содержимым"},
        413: {"description": "Тело запроса превышает 65536 байт"},
    },
)
async def ingest(notification: NotificationIn, response: Response, session: Session):
    if not can_store(notification.app_name, notification.title, notification.text):
        response.status_code = 200
        return NotificationReceipt(id=None, status="skipped", reason="privacy_policy")
    if notification.timestamp < clock.iso_utc(cutoff()):
        response.status_code = 200
        return NotificationReceipt(id=None, status="skipped", reason="expired")
    try:
        row_id, created = await save_notification(session, notification)
    except IdentityConflict:
        raise HTTPException(409, "event_id уже использован для другого уведомления") from None
    response.status_code = 201 if created else 200
    return NotificationReceipt(id=row_id, status="stored" if created else "duplicate")


@router.get("", response_model=NotificationPage)
async def list_notifications(
    session: Session,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    category: Annotated[str | None, Query(max_length=64, pattern=r"^[a-z][a-z0-9_]*$")] = None,
):
    condition = visible_since(cutoff())
    if category is not None:
        condition = condition & (NotificationRaw.category == category)
    # Один read transaction обеспечивает согласованность total и страницы.
    total = await session.scalar(select(func.count()).select_from(NotificationRaw).where(condition))
    rows = await session.scalars(
        select(NotificationRaw)
        .where(condition)
        .order_by(NotificationRaw.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return NotificationPage(items=[serialize(row) for row in rows], total=total)


@router.get("/{notification_id}", response_model=NotificationOut)
async def get_notification(
    notification_id: Annotated[int, Path(gt=0, le=9_223_372_036_854_775_807)],
    session: Session,
):
    row = await session.scalar(
        select(NotificationRaw).where(
            NotificationRaw.id == notification_id, visible_since(cutoff())
        )
    )
    if row is None:
        raise HTTPException(404, "Уведомление не найдено")
    return serialize(row)
