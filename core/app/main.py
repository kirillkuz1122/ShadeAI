import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.notification_body import NotificationBodyLimit
from app.api.v1 import ha, health, notifications
from app.core.config import settings
from app.db.base import init_db
from app.services.notification.maintenance import cleanup, cleanup_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await cleanup()
    maintenance = asyncio.create_task(cleanup_loop())
    try:
        yield
    finally:
        maintenance.cancel()
        with suppress(asyncio.CancelledError):
            await maintenance


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

    return app


app = create_app()
