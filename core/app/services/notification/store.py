import hashlib
import json
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.db.models import NotificationRaw
from app.schemas import NotificationIn, NotificationOut
from app.services.notification.privacy import allowed_apps, can_store


def cutoff() -> datetime:
    return clock.utcnow() - timedelta(days=settings.notification_retention_days)


def identity(notification: NotificationIn) -> tuple[str, str]:
    payload = notification.model_dump(mode="json", exclude={"event_id"})
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode()).hexdigest()
    key = f"event:{notification.event_id}" if notification.event_id else f"sha256:{digest}"
    return key, digest


def visible_since(since: datetime):
    return and_(
        NotificationRaw.created_at >= since,
        NotificationRaw.timestamp >= clock.iso_utc(since),
        NotificationRaw.payload_hash.is_not(None),
        NotificationRaw.app_name.in_(allowed_apps()),
    )


async def purge_expired(session: AsyncSession, since: datetime) -> None:
    await session.execute(
        delete(NotificationRaw).where(
            or_(
                NotificationRaw.created_at < since,
                and_(
                    NotificationRaw.payload_hash.is_not(None),
                    NotificationRaw.timestamp < clock.iso_utc(since),
                ),
            )
        )
    )


class IdentityConflict(Exception):
    pass


async def save_notification(
    session: AsyncSession, notification: NotificationIn
) -> tuple[int, bool]:
    key, digest = identity(notification)
    async with session.begin():
        # Первая операция — запись: параллельные повторы не повышают read-lock до write-lock.
        await purge_expired(session, cutoff())
        row_id = (
            await session.execute(
                insert(NotificationRaw)
                .values(
                    **notification.model_dump(exclude={"event_id"}),
                    created_at=clock.utcnow(),
                    dedupe_key=key,
                    payload_hash=digest,
                )
                .on_conflict_do_nothing(index_elements=["dedupe_key"])
                .returning(NotificationRaw.id)
            )
        ).scalar_one_or_none()
        if row_id is not None:
            return row_id, True
        row = (
            await session.execute(
                select(NotificationRaw.id, NotificationRaw.payload_hash).where(
                    NotificationRaw.dedupe_key == key
                )
            )
        ).one()
        if row.payload_hash != digest:
            raise IdentityConflict
        return row.id, False


def serialize(row: NotificationRaw) -> NotificationOut:
    event_id = (
        row.dedupe_key.removeprefix("event:") if row.dedupe_key.startswith("event:") else None
    )
    return NotificationOut(
        id=row.id,
        app_name=row.app_name,
        title=row.title,
        text=row.text,
        timestamp=row.timestamp,
        priority=row.priority,
        event_id=event_id,
        status="processed" if row.processing_status == "processed" else "stored",
        processing_status=row.processing_status,
        processing_attempts=row.processing_attempts,
        processing_error_code=row.processing_error_code,
        processing_started_at=(
            clock.iso_utc(row.processing_started_at.replace(tzinfo=UTC))
            if row.processing_started_at
            else None
        ),
        processing_finished_at=(
            clock.iso_utc(row.processing_finished_at.replace(tzinfo=UTC))
            if row.processing_finished_at
            else None
        ),
        category=row.category,
        processed_data=(
            json.loads(row.extracted_data_json)
            if row.processing_status == "processed" and row.extracted_data_json
            else None
        ),
        created_at=clock.iso_utc(row.created_at.replace(tzinfo=UTC)),
    )


async def maintain_notifications(session: AsyncSession) -> None:
    since = cutoff()
    last_id = 0
    while True:
        await purge_expired(session, since)
        await session.execute(
            delete(NotificationRaw).where(
                or_(
                    NotificationRaw.app_name.not_in(allowed_apps()),
                    # Прежний скелет не ограничивал размер: отсечь до загрузки строк в Python.
                    func.length(NotificationRaw.title) > 512,
                    func.length(NotificationRaw.text) > 8192,
                )
            )
        )
        rows = (
            await session.execute(
                select(
                    NotificationRaw.id,
                    NotificationRaw.app_name,
                    NotificationRaw.title,
                    NotificationRaw.text,
                    NotificationRaw.timestamp,
                    NotificationRaw.priority,
                )
                .where(NotificationRaw.payload_hash.is_(None), NotificationRaw.id > last_id)
                .order_by(NotificationRaw.id)
                .limit(256)
            )
        ).all()
        for row in rows:
            last_id = row.id
            try:
                notification = NotificationIn.model_validate(
                    {k: v for k, v in row._mapping.items() if k != "id"}
                )
            except ValidationError:
                await session.execute(delete(NotificationRaw).where(NotificationRaw.id == row.id))
                continue
            if not can_store(
                notification.app_name, notification.title, notification.text
            ) or notification.timestamp < clock.iso_utc(since):
                await session.execute(delete(NotificationRaw).where(NotificationRaw.id == row.id))
                continue
            key, digest = identity(notification)
            existing = await session.scalar(
                select(NotificationRaw.id).where(NotificationRaw.dedupe_key == key)
            )
            if existing is not None:
                await session.execute(delete(NotificationRaw).where(NotificationRaw.id == row.id))
            else:
                await session.execute(
                    update(NotificationRaw)
                    .where(NotificationRaw.id == row.id)
                    .values(
                        timestamp=notification.timestamp,
                        dedupe_key=key,
                        payload_hash=digest,
                        category=None,
                        extracted_data_json=None,
                        is_processed=0,
                        processing_status="pending",
                        processing_attempts=0,
                        processing_error_code=None,
                        processing_started_at=None,
                        processing_finished_at=None,
                    )
                )
        await session.commit()
        if not rows:
            return
