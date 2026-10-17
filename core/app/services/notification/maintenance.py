import asyncio
import logging

from app.db import base
from app.services.ha_bridge.audit import maintain_events
from app.services.notification.store import maintain_notifications

logger = logging.getLogger("shade.maintenance")


async def cleanup() -> None:
    async with base.async_session() as session:
        await maintain_notifications(session)
        await maintain_events(session)


async def cleanup_loop() -> None:
    while True:
        await asyncio.sleep(3600)
        try:
            await cleanup()
        except Exception:
            # Исключения SQLAlchemy могут содержать параметры; не писать данные в лог.
            logger.error("Очистка уведомлений не выполнена; повтор через час")
