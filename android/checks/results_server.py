"""Настоящий изолированный Core19 с синтетическими переходами результата, без LLM/HA."""

import json
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[2]
API_KEY = "task19-synthetic-emulator-owner-00001"
TEXT = "Синтетический заказ: доставка завтра в 18:00 в Пункт выдачи"
PRIVATE = "synthetic-raw-error-never-display"


def main():
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(
        prefix="results-android-", dir=ROOT / "core/.pytest_cache"
    ) as folder:
        os.chdir(folder)
        os.environ.clear()
        os.environ.update(
            SHADE_API_KEY=API_KEY,
            DB_URL="sqlite+aiosqlite:///synthetic.db",
            HA_BASE_URL="http://127.0.0.1:1",
            HA_TIMEOUT_SECONDS="0.1",
            LLM_ENABLED="false",
            NOTIFICATION_PROCESSOR="disabled",
            LOG_DIR="./logs",
        )
        sys.path.insert(0, str(ROOT / "core"))
        from sqlalchemy import delete, update

        from app.core import clock
        from app.db import base
        from app.db.models import NotificationRaw
        from app.main import create_app
        from app.schemas import NotificationIn
        from app.services.notification.extraction import (
            ExtractedEntities,
            ExtractedNotification,
            ExtractedTime,
        )
        from app.services.notification.store import save_notification

        app = create_app()
        original = app.router.lifespan_context
        control = dict(identity=None, reads=0, mode="normal", commands=0)

        @asynccontextmanager
        async def lifespan(value):
            async with original(value):
                for number in range(1, 26):
                    async with base.async_session() as session:
                        identity, _ = await save_notification(
                            session,
                            NotificationIn(
                                app_name="ru.ozon.app.android",
                                title=f"Стенд Core {number}",
                                text=TEXT + f" · запись{number}",
                                priority="default",
                                event_id=uuid4(),
                                timestamp=clock.iso_utc(clock.utcnow()),
                            ),
                        )
                    control["identity"] = identity
                yield

        app.router.lifespan_context = lifespan

        @app.middleware("http")
        async def observe(request: Request, next):
            path = request.url.path
            if path.startswith("/api/v1/notifications"):
                control["reads"] += 1
                if control["mode"] == "denied":
                    return JSONResponse({"detail": PRIVATE}, status_code=401)
            if path.endswith("/command") or path == "/api/v1/ha/action":
                control["commands"] += 1
            return await next(request)

        @app.get("/checks/state")
        async def state():
            return control

        @app.post("/checks/mode/{mode}")
        async def mode(mode: str):
            assert mode in {
                "normal",
                "denied",
                "processing",
                "processed",
                "diagnostic",
                "unsupported",
                "failed",
                "deleted",
            }
            if mode in {"normal", "denied"}:
                control["mode"] = mode
                return {"ok": True}
            async with base.async_session() as session, session.begin():
                await session.connection(execution_options={"sqlite_immediate": True})
                condition = NotificationRaw.id == control["identity"]
                if mode == "deleted":
                    await session.execute(delete(NotificationRaw).where(condition))
                    return {"ok": True}
                values = dict(
                    processing_status="processed",
                    is_processed=1,
                    processing_attempts=1,
                    processing_error_code=None,
                    category="delivery",
                )
                parsed = ExtractedNotification(
                    category="delivery",
                    priority="default",
                    intent="delivery_event",
                    entities=ExtractedEntities(
                        subject="Заказ", location="Пункт выдачи", service="Ozon"
                    ),
                    time=ExtractedTime(
                        source="завтра в 18:00",
                        timezone="Asia/Yekaterinburg",
                        at=clock.iso_utc(
                            (clock.utcnow() + timedelta(days=1)).replace(
                                hour=13, minute=0, second=0, microsecond=0
                            )
                        ),
                        date=None,
                        resolution="exact",
                    ),
                )
                data = parsed.model_dump()
                if mode == "processing":
                    values.update(processing_status="processing", is_processed=0)
                    data = None
                elif mode == "diagnostic":
                    data = {"processor": "diagnostic", "llm": False}
                elif mode == "unsupported":
                    data["schema_version"] = 999
                elif mode == "failed":
                    values.update(
                        processing_status="failed", processing_error_code=PRIVATE, is_processed=0
                    )
                    data = None
                values["extracted_data_json"] = json.dumps(data) if data else None
                await session.execute(update(NotificationRaw).where(condition).values(**values))
            return {"ok": True}

        try:
            uvicorn.run(app, host="127.0.0.1", port=8003, access_log=False, log_level="warning")
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    main()
