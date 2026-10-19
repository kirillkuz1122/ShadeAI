"""Изолированный настоящий Core26 для Android, только синтетические доставки/HA."""

import json
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[2]
API_KEY = "task26-synthetic-emulator-owner-00001"
KEYPAD_KEY = "task26-synthetic-emulator-keypad-0001"
ENTITY = "lock.synthetic_delivery"
TEXT = "synthetic-private-delivery-context"


def main():
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(
        prefix="task26-android-", dir=ROOT / "core/.pytest_cache"
    ) as folder:
        os.chdir(folder)
        os.environ.clear()
        os.environ.update(
            SHADE_API_KEY=API_KEY,
            DB_URL="sqlite+aiosqlite:///synthetic.db",
            HA_TOKEN="",
            HA_BASE_URL="http://127.0.0.1:1",
            ACCESS_ENABLED="true",
            ACCESS_ALLOWED_LOCKS=json.dumps([ENTITY]),
            ACCESS_KEYPAD_TOKEN=KEYPAD_KEY,
            LLM_ENABLED="false",
            NOTIFICATION_PROCESSOR="disabled",
            LOG_DIR="./logs",
        )
        sys.path.insert(0, str(ROOT / "core"))
        from sqlalchemy import update

        from app.core import clock
        from app.db import base
        from app.db.models import NotificationRaw
        from app.main import create_app
        from app.schemas import NotificationIn
        from app.services.ha_bridge.client import HAError
        from app.services.ha_bridge.models import HAState
        from app.services.notification.extraction import (
            ExtractedEntities,
            ExtractedNotification,
            ExtractedTime,
        )
        from app.services.notification.store import save_notification

        control = dict(mode="normal", commands=0, sources=[])

        class HA:
            async def call_service(self, domain, action, entity, params):
                assert (domain, action, entity, params) == (
                    "lock",
                    "unlock",
                    ENTITY,
                    {},
                )
                control["commands"] += 1
                if control["mode"] == "unknown":
                    raise HAError("HA_TIMEOUT", 504, "unknown")
                return []

            async def get_state(self, entity):
                assert entity == ENTITY
                now = datetime.now(UTC).isoformat()
                return HAState(
                    entity_id=entity,
                    state="unlocked",
                    attributes={},
                    last_changed=now,
                    last_updated=now,
                )

        app = create_app()
        original = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(value):
            async with original(value):
                value.state.access.client = HA()
                for index in range(1, 4):
                    item = NotificationIn(
                        app_name="ru.ozon.app.android",
                        title="Доставка",
                        text=TEXT + str(index),
                        timestamp=clock.iso_utc(clock.utcnow()),
                        priority="default",
                        event_id=uuid4(),
                    )
                    async with base.async_session() as session:
                        identity, _ = await save_notification(session, item)
                    parsed = ExtractedNotification(
                        category="delivery",
                        priority="default",
                        intent="delivery_event",
                        entities=ExtractedEntities(subject="Посылка", location=None, service=None),
                        time=ExtractedTime(
                            source=None,
                            timezone="UTC",
                            at=None,
                            date=None,
                            resolution="absent",
                        ),
                    )
                    async with base.async_session() as session, session.begin():
                        await session.execute(
                            update(NotificationRaw)
                            .where(NotificationRaw.id == identity)
                            .values(
                                processing_status="processed",
                                is_processed=1,
                                category="delivery",
                                extracted_data_json=parsed.model_dump_json(),
                            )
                        )
                    control["sources"].append(identity)
                yield

        app.router.lifespan_context = lifespan

        @app.middleware("http")
        async def denied(request: Request, next):
            if control["mode"] == "denied" and request.url.path.startswith("/api/v1/access"):
                return JSONResponse({"detail": "private synthetic error body"}, status_code=401)
            return await next(request)

        @app.get("/checks/state")
        async def state():
            return control

        @app.post("/checks/mode/{mode}")
        async def mode(mode: str):
            assert mode in {"normal", "unknown", "denied"}
            control["mode"] = mode
            return {"ok": True}

        try:
            uvicorn.run(app, host="127.0.0.1", port=8003, log_level="warning", access_log=False)
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    main()
