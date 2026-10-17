import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.notification_body import NotificationBodyLimit
from app.api.v1 import devices, events, ha, health, notifications
from app.core.config import settings
from app.core.logging import local_logging
from app.db import base
from app.db.base import init_db
from app.services.ha_bridge.audit import maintain_events
from app.services.ha_bridge.client import HAClient
from app.services.notification.maintenance import cleanup, cleanup_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    with local_logging() as logger:
        await init_db()
        await cleanup()
        async with base.async_session() as session:
            await maintain_events(session, recover=True)
        client = HAClient()
        app.state.ha_client = client
        maintenance = asyncio.create_task(cleanup_loop())
        logger.info("Core started")
        try:
            yield
        finally:
            maintenance.cancel()
            with suppress(asyncio.CancelledError):
                await maintenance
            await client.close()
            logger.info("Core stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(NotificationBodyLimit)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Ошибки Pydantic по умолчанию возвращают исходный input, включая приватный текст.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {
                        "type": error["type"],
                        "loc": [
                            part
                            if part
                            in {
                                "body",
                                "query",
                                "path",
                                "app_name",
                                "title",
                                "text",
                                "timestamp",
                                "priority",
                                "event_id",
                                "limit",
                                "offset",
                                "category",
                                "notification_id",
                                "domain",
                                "entity_id",
                                "service",
                                "action",
                                "params",
                                "data",
                                "from",
                                "to",
                                "type",
                            }
                            else "_"
                            for part in error["loc"]
                        ],
                        "msg": "Неверные параметры запроса",
                    }
                    for error in exc.errors()
                ]
            },
        )

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(notifications.router, prefix="/api/v1")
    app.include_router(ha.router, prefix="/api/v1")
    app.include_router(devices.router, prefix="/api/v1")
    app.include_router(events.router, prefix="/api/v1")

    return app


app = create_app()
