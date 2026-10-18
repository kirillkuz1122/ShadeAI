import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.core import clock
from app.core.config import settings
from app.db import base
from app.db.models import NotificationRaw
from app.schemas import NotificationIn
from app.services.notification.privacy import can_store
from app.services.notification.processor import ProcessingResult, process_notification
from app.services.notification.store import cutoff, visible_since

Processor = Callable[[NotificationIn], Awaitable[ProcessingResult]]
logger = logging.getLogger("shade")
POLL_SECONDS = 1.0


@dataclass(frozen=True)
class Work:
    id: int
    digest: str
    attempt: int
    notification: NotificationIn


class NotificationWorker:
    def __init__(self, processor: Processor | None = None):
        self.processor = processor or (
            process_notification if settings.notification_processor == "diagnostic" else None
        )
        self.queue: asyncio.Queue[int] = asyncio.Queue(maxsize=settings.notification_queue_size)
        self.wake = asyncio.Event()
        self.stopping = False
        self.task: asyncio.Task | None = None
        self.status = "starting"
        self.recover_needed = False

    async def start(self) -> None:
        await self.recover()
        self.status = "idle" if self.processor else "disabled"
        if self.processor:
            self.task = asyncio.create_task(self.run(), name="notification-worker")

    async def recover(self) -> None:
        async with base.async_session() as session, session.begin():
            await session.execute(
                update(NotificationRaw)
                .where(NotificationRaw.processing_status == "processing")
                .values(
                    processing_status="pending",
                    processing_error_code="PROCESSING_INTERRUPTED",
                    processing_started_at=None,
                    processing_finished_at=None,
                    is_processed=0,
                    category=None,
                    extracted_data_json=None,
                )
            )
        self.recover_needed = False

    def notify(self) -> None:
        self.wake.set()

    async def stop(self) -> None:
        self.stopping = True
        self.wake.set()
        if self.task and not self.task.cancelled():
            try:
                await asyncio.wait_for(
                    asyncio.shield(self.task), settings.notification_shutdown_seconds
                )
            except TimeoutError:
                self.task.cancel()
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass
        self.status = "stopped"

    async def refill(self) -> None:
        async with base.async_session() as session:
            ids = (
                await session.scalars(
                    select(NotificationRaw.id)
                    .where(NotificationRaw.processing_status == "pending", visible_since(cutoff()))
                    .order_by(NotificationRaw.id)
                    .limit(self.queue.maxsize)
                )
            ).all()
        for row_id in ids:
            self.queue.put_nowait(row_id)

    async def claim(self, row_id: int) -> Work | None:
        async with base.async_session() as session, session.begin():
            # UPDATE — первая операция: нет повышения SQLite read-lock до write-lock.
            row = await session.scalar(
                update(NotificationRaw)
                .where(
                    NotificationRaw.id == row_id,
                    NotificationRaw.processing_status == "pending",
                    visible_since(cutoff()),
                )
                .values(
                    processing_status="processing",
                    processing_attempts=NotificationRaw.processing_attempts + 1,
                    processing_error_code=None,
                    processing_started_at=clock.utcnow(),
                    processing_finished_at=None,
                    is_processed=0,
                    extracted_data_json=None,
                    category=None,
                )
                .returning(NotificationRaw)
            )
            if row is None:
                return None
            if not can_store(row.app_name, row.title, row.text):
                await session.execute(delete(NotificationRaw).where(NotificationRaw.id == row_id))
                return None
            try:
                notification = NotificationIn(
                    app_name=row.app_name,
                    title=row.title,
                    text=row.text,
                    timestamp=row.timestamp,
                    priority=row.priority,
                )
            except ValidationError:
                row.processing_status = "failed"
                row.processing_error_code = "INVALID_NOTIFICATION"
                row.processing_finished_at = clock.utcnow()
                return None
            return Work(row.id, row.payload_hash, row.processing_attempts, notification)

    async def finish(self, work: Work, result: ProcessingResult | None, error: str | None) -> None:
        async with base.async_session() as session, session.begin():
            # Удалённую/просроченную/снятую с допуска строку результат не возрождает.
            await session.execute(
                update(NotificationRaw)
                .where(
                    NotificationRaw.id == work.id,
                    NotificationRaw.payload_hash == work.digest,
                    NotificationRaw.processing_status == "processing",
                    NotificationRaw.processing_attempts == work.attempt,
                    visible_since(cutoff()),
                )
                .values(
                    processing_status="failed" if error else "processed",
                    processing_error_code=error,
                    processing_finished_at=clock.utcnow(),
                    is_processed=0 if error else 1,
                    category=None,
                    extracted_data_json=result.model_dump_json() if result else None,
                )
            )

    async def process(self, work: Work) -> None:
        result, error = None, None
        raw, payload = None, None
        try:
            async with asyncio.timeout(settings.notification_processing_timeout_seconds):
                raw = await self.processor(work.notification)
            # Проверяем даже BaseModel: model_construct не является доверенной валидацией.
            payload = raw.model_dump() if isinstance(raw, ProcessingResult) else raw
            result = ProcessingResult.model_validate(payload)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            error = "PROCESSOR_TIMEOUT"
        except ValidationError:
            error = "INVALID_RESULT"
        except Exception:
            error = "PROCESSOR_ERROR"
        finally:
            raw, payload = None, None
        while True:
            try:
                await self.finish(work, result, error)
                return
            except SQLAlchemyError:
                self.status = "storage_error"
                logger.error("Notification worker STORAGE_ERROR")
                # Храним один ограниченный результат; не вычисляем его повторно до commit.
                await asyncio.sleep(POLL_SECONDS)

    async def run(self) -> None:
        try:
            while not self.stopping:
                self.wake.clear()
                try:
                    if self.recover_needed:
                        await self.recover()
                    if self.queue.empty():
                        await self.refill()
                    if self.queue.empty():
                        self.status = "idle"
                        try:
                            await asyncio.wait_for(self.wake.wait(), POLL_SECONDS)
                        except TimeoutError:
                            pass
                        continue
                    row_id = self.queue.get_nowait()
                    try:
                        work = await self.claim(row_id)
                        if work:
                            self.status = "processing"
                            await self.process(work)
                    finally:
                        self.queue.task_done()
                except SQLAlchemyError:
                    self.recover_needed = True
                    self.status = "storage_error"
                    logger.error("Notification worker STORAGE_ERROR")
                    await asyncio.sleep(POLL_SECONDS)
        finally:
            while not self.queue.empty():
                self.queue.get_nowait()
                self.queue.task_done()
            self.status = "stopped"
