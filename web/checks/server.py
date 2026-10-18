"""Изолированный Core для браузерной приёмки; только синтетические данные и HA mock."""

import os
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_KEY = "task07-browser-test-key-000000000"


def main():
    cache = ROOT / "core/.pytest_cache"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="task07-browser-", dir=cache) as scratch:
        os.chdir(scratch)
        os.environ.update(
            SHADE_API_KEY=API_KEY,
            DB_URL="sqlite+aiosqlite:///./browser.db",
            HA_BASE_URL="http://ha.test:8123",
            HA_TOKEN="task07-ha-synthetic-token",
            HA_TIMEOUT_SECONDS="0.2",
            HA_TELEMETRY_ENTITIES="[]",
            NOTIFICATION_PROCESSOR="disabled",
            NOTIFICATION_QUEUE_SIZE="64",
            NOTIFICATION_PROCESSING_TIMEOUT_SECONDS="30",
            NOTIFICATION_SHUTDOWN_SECONDS="5",
            EVENT_RETENTION_DAYS="90",
            LOG_DIR="./logs",
            LOG_MAX_BYTES="1048576",
            LOG_BACKUP_COUNT="3",
            NOTIFICATION_RETENTION_DAYS="30",
            NOTIFICATION_ALLOWED_APPS='["ru.ozon.app.android"]',
            CORS_ORIGINS='["http://localhost:5173","http://127.0.0.1:5173"]',
            LLM_MODEL_PATH="./missing-test-model.gguf",
        )
        sys.path.insert(0, str(ROOT / "core"))
        import httpx
        import uvicorn
        from app.db import base
        from app.main import create_app, lifespan

        def mock(request):
            assert request.url.host == "ha.test"
            if request.method == "GET" and request.url.path == "/api/":
                raise httpx.ConnectError("Тестовый HA недоступен")
            if request.method == "POST":
                import json

                level = json.loads(request.content).get("brightness", 0)
                if level == 1:
                    return httpx.Response(401)
                if level == 2:
                    raise httpx.ReadTimeout("Тестовый timeout")
                return httpx.Response(200, json=[])
            return httpx.Response(
                200,
                json={
                    "entity_id": "light.test",
                    "state": "on",
                    "attributes": {},
                    "last_changed": datetime.now(UTC).isoformat(),
                    "last_updated": datetime.now(UTC).isoformat(),
                },
            )

        @asynccontextmanager
        async def fixture_lifespan(app):
            async with lifespan(app):
                await app.state.ha_client._client.aclose()
                app.state.ha_client._client = httpx.AsyncClient(
                    base_url="http://ha.test:8123",
                    transport=httpx.MockTransport(mock),
                    trust_env=False,
                )
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app),
                    base_url="http://fixture",
                    headers={"Authorization": f"Bearer {API_KEY}"},
                    trust_env=False,
                ) as client:
                    for number in range(45):
                        response = await client.post(
                            "/api/v1/notifications",
                            json={
                                "app_name": "ru.ozon.app.android",
                                "title": f"Заказ №{1001 + number} готов к получению",
                                "text": "Посылка прибыла в пункт выдачи. Заберите заказ в удобное время. "
                                + (
                                    "Длинный текст для проверки переноса. " * 40
                                    if number == 44
                                    else ""
                                ),
                                "timestamp": (
                                    datetime.now(UTC) - timedelta(minutes=45 - number)
                                ).isoformat(),
                                "priority": "default",
                            },
                        )
                        assert response.status_code == 201, response.text
                    for number in range(24):
                        response = await client.post(
                            "/api/v1/devices/light.test/command",
                            json={
                                "action": "turn_on",
                                "params": {"brightness": number % 3},
                            },
                        )
                        assert response.status_code in {200, 503, 504}
                yield
            await base.engine.dispose()

        app = create_app()
        app.router.lifespan_context = fixture_lifespan
        uvicorn.run(
            app, host="127.0.0.1", port=8000, log_level="warning", access_log=False
        )


if __name__ == "__main__":
    main()
