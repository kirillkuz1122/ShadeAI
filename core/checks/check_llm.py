"""Изолированный полный Core + реальный LLM-процесс; модель указать явно."""

import argparse
import asyncio
import json
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))


async def scenario(model, expected_error=None):
    import httpx

    from app import main
    from app.core import clock
    from app.services.ha_bridge.client import HAClient

    key = os.environ["SHADE_API_KEY"]
    original = HAClient

    class FakeHA(original):
        def __init__(self):
            super().__init__()
            self.old = self._client

            async def handle(request):
                if request.url.path == "/api/":
                    return httpx.Response(200, json={"message": "API running."})
                return httpx.Response(503)

            self._client = httpx.AsyncClient(
                transport=httpx.MockTransport(handle),
                base_url="http://ha.synthetic",
                trust_env=False,
            )

        async def close(self):
            await self.old.aclose()
            await super().close()

    main.HAClient = FakeHA
    app = main.create_app()
    async with main.lifespan(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://stand",
            headers={"Authorization": f"Bearer {key}"},
        ) as client:
            # API доступен пока нативная загрузка выполняется в отдельном процессе.
            started = time.monotonic()
            response = await client.get("/api/v1/health")
            assert response.status_code == 200
            assert time.monotonic() - started < 1
            async with asyncio.timeout(180):
                while app.state.llm.status in {"not_loaded", "loading"}:
                    await asyncio.sleep(0.02)
            if app.state.llm.status != "ready":
                if expected_error:
                    assert app.state.llm.status == expected_error, app.state.llm.status
                    assert (await client.get("/api/v1/notifications")).status_code == 200
                    assert (
                        await client.post(
                            "/api/v1/notifications",
                            json={
                                "app_name": "ru.ozon.app.android",
                                "title": "Синтетика",
                                "text": "Посылка прибыла",
                                "timestamp": clock.iso_utc(clock.utcnow()),
                            },
                        )
                    ).status_code == 201
                    print(
                        json.dumps(
                            {
                                "result": "PASS",
                                "check": "Core/LLM-fallback",
                                "error": app.state.llm.status,
                            }
                        )
                    )
                    return
                raise RuntimeError(app.state.llm.status)
            assert expected_error is None
            task = asyncio.create_task(
                app.state.llm.generate(
                    [
                        {"role": "system", "content": "Отвечай по-русски одним предложением."},
                        {"role": "user", "content": "Что такое локальный умный дом?"},
                    ]
                )
            )
            started = time.monotonic()
            assert (await client.get("/api/v1/health")).json()["llm_status"] == "ready"
            assert (
                await client.post(
                    "/api/v1/notifications",
                    json={
                        "app_name": "ru.ozon.app.android",
                        "title": "Синтетика",
                        "text": "Посылка прибыла",
                        "timestamp": clock.iso_utc(clock.utcnow()),
                    },
                )
            ).status_code == 201
            assert time.monotonic() - started < 1
            result = await task
            assert result.content and result.completion_tokens > 0
            # Отмена обрывает нативный процесс, а не оставляет CPU/RAM занятой моделью.
            running = asyncio.create_task(
                app.state.llm.generate(
                    [
                        {
                            "role": "user",
                            "content": "Напиши длинный список из ста русских предложений.",
                        }
                    ]
                )
            )
            await asyncio.sleep(0.02)
            process = app.state.llm.process
            running.cancel()
            try:
                await running
            except asyncio.CancelledError:
                pass
            assert app.state.llm.process is None and process.returncode is not None
            await app.state.llm.load()
            assert app.state.llm.status == "ready"
            print(
                json.dumps(
                    {
                        "result": "PASS",
                        "check": "Core/live-LLM/HTTP/cancel/reload",
                        "model": model.name,
                        "completion_tokens": result.completion_tokens,
                        "load": app.state.llm.info.model_dump(),
                    },
                    ensure_ascii=False,
                )
            )
    assert app.state.llm.process is None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--expected-error")
    args = parser.parse_args()
    model = args.model.resolve(strict=True)
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="task16-core-", dir=CORE / ".pytest_cache") as scratch:
        os.chdir(scratch)
        os.environ.update(
            {
                "SHADE_API_KEY": secrets.token_urlsafe(32),
                "DB_URL": "sqlite+aiosqlite:///./check.db",
                "LOG_DIR": "./logs",
                "HA_BASE_URL": "http://ha.synthetic",
                "HA_TOKEN": "synthetic-ha-token",
                "HA_TELEMETRY_ENTITIES": "[]",
                "NOTIFICATION_PROCESSOR": "disabled",
                "LLM_ENABLED": "true",
                "LLM_MODEL_PATH": str(model),
                "LLM_CONTEXT_SIZE": "1024",
                "LLM_THREADS": "2",
                "LLM_MAX_TOKENS": "128",
                "LLM_LOAD_TIMEOUT_SECONDS": "180",
                "LLM_INFERENCE_TIMEOUT_SECONDS": "60",
                "LLM_MEMORY_LIMIT_MB": "2304",
                "CORS_ORIGINS": "[]",
                "NOTIFICATION_ALLOWED_APPS": '["ru.ozon.app.android"]',
            }
        )
        try:
            asyncio.run(scenario(model, args.expected_error))
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    main()
