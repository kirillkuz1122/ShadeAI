import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ha_deps import get_ha_client
from app.core.config import settings
from app.db.base import get_session
from app.services.ha_bridge.client import HAClient, HAError

router = APIRouter(tags=["system"])
_started_at = time.monotonic()


def database_size() -> int | None:
    database = make_url(settings.db_url).database
    if not database or database == ":memory:":
        return 0
    try:
        path = Path(database)
        return sum(
            file.stat().st_size for file in [path, Path(str(path) + "-wal")] if file.is_file()
        )
    except OSError:
        return None


@router.get("/health")
async def health(
    response: Response,
    client: Annotated[HAClient, Depends(get_ha_client)],
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
) -> dict:
    try:
        await session.execute(text("SELECT 1"))
        db_connected = True
    except SQLAlchemyError:
        await session.rollback()
        db_connected = False
    # Не держать read-транзакцию БД во время сетевого ожидания HA.
    if db_connected:
        await session.rollback()
    try:
        await client.ping()
        ha_status = "connected"
    except HAError as exc:
        ha_status = exc.code
    ha_connected = ha_status == "connected"
    status = "ok" if db_connected and ha_connected else "degraded" if db_connected else "error"
    response.status_code = 200 if db_connected else 503
    size = database_size()
    return dict(
        status=status,
        uptime=int(time.monotonic() - _started_at),
        ha_connected=ha_connected,
        ha_status=ha_status,
        db_connected=db_connected,
        llm_status=request.app.state.llm.status,
        db_size=f"{size / 1024 / 1024:.1f} MB" if size is not None else "unknown",
        db_size_bytes=size,
        services={
            "database": "ready" if db_connected else "unavailable",
            "home_assistant": ha_status,
            "llm": request.app.state.llm.status,
            "notification_worker": request.app.state.notification_worker.status,
            "analytics": request.app.state.analytics.status,
            "suggestions": request.app.state.suggestions.status,
        },
    )
