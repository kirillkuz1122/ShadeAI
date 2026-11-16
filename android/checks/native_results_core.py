"""TASK-19: один временный SQLite store между Android, offline Qwen и клиентами."""

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"
SCRATCH = CORE / ".pytest_cache/task19-native-work"
KEY = "task19-native-only-synthetic-key-01"
BASE = "http://127.0.0.1:8003"
MODEL = CORE / "models/qwen2.5-1.5b-instruct-q4_k_m.gguf"


CONTROL_TITLE = "Курьер в пути"


async def infer(app, lifespan, *, control=False):
    import httpx

    async with (
        lifespan(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url=BASE,
            headers={"Authorization": "Bearer " + KEY},
        ) as client,
    ):
        async with asyncio.timeout(100):
            while app.state.llm.status in {"loading", "not_loaded"}:
                await asyncio.sleep(0.1)
            assert app.state.llm.status == "ready", app.state.llm.status
            pin = json.loads((ROOT / "scripts/models.json").read_text())["qwen"]
            assert app.state.llm.info.sha256 == pin["sha256"]
            if control:
                previous = (await client.get("/api/v1/notifications")).json()["items"]
                assert len(previous) == 2 and all(
                    row["processing_status"] in {"processed", "failed"}
                    for row in previous
                )
                response = await client.post(
                    "/api/v1/notifications",
                    json={
                        "app_name": "ru.ozon.app.android",
                        "title": CONTROL_TITLE,
                        "text": "Курьер привезёт заказ через 8 минут, будьте на месте.",
                        "timestamp": datetime.now(UTC).isoformat(),
                        "event_id": str(uuid4()),
                    },
                )
                response.raise_for_status()
                assert response.status_code == 201
            while True:
                response = await client.get("/api/v1/notifications")
                response.raise_for_status()
                rows = response.json()["items"]
                assert len(rows) == (3 if control else 2) and all(
                    row["event_id"] for row in rows
                )
                expected = {
                    "Синтетическая доставка order",
                    "Синтетическая доставка big",
                }
                if control:
                    expected.add(CONTROL_TITLE)
                assert {row["title"] for row in rows} == expected
                if all(
                    row["processing_status"] in {"processed", "failed"} for row in rows
                ):
                    break
                await asyncio.sleep(0.2)
            for row in rows:
                assert row["processing_attempts"] == 1
                result = row["processed_data"]
                if result is not None:
                    assert (
                        result["llm"] is True and result["action_authorized"] is False
                    )
            commands = await client.get("/api/v1/events")
            commands.raise_for_status()
            assert commands.json()["total"] == 0
            print(
                json.dumps(
                    {
                        "rows": [
                            {
                                k: row[k]
                                for k in (
                                    "id",
                                    "event_id",
                                    "processing_status",
                                    "processing_error_code",
                                    "category",
                                )
                            }
                            for row in rows
                        ],
                        "control_via_api": control,
                        "model_sha256": app.state.llm.info.sha256,
                        "ha_audit_count": 0,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("serve", "infer", "infer-control"))
    args = parser.parse_args()
    assert SCRATCH.is_dir() and SCRATCH.resolve() == SCRATCH
    assert not (SCRATCH / "capture.db").is_symlink()
    assert not (SCRATCH / ".env").exists()
    native = args.phase != "serve"
    if native:
        assert (SCRATCH / "capture.db").is_file() and MODEL.is_file()
        # Отдельный network namespace обязателен для native-фазы.
        assert Path("/proc/net/dev").read_text().count(":") == 1
    os.chdir(SCRATCH)
    os.environ.clear()
    os.environ.update(
        SHADE_API_KEY=KEY,
        DB_URL="sqlite+aiosqlite:///./capture.db",
        LOG_DIR="./logs",
        HA_BASE_URL="http://127.0.0.1:1",
        NOTIFICATION_ALLOWED_APPS='["ru.ozon.app.android"]',
        WEB_DIST_PATH=str(ROOT / "web/dist"),
        NOTIFICATION_PROCESSOR="llm" if native else "disabled",
        LLM_ENABLED="true" if native else "false",
        LLM_MODEL_PATH=str(MODEL),
        LLM_CONTEXT_SIZE="2048",
        LLM_THREADS="2",
        LLM_MAX_TOKENS="256",
        LLM_MEMORY_LIMIT_MB="2304",
    )
    sys.path.insert(0, str(CORE))
    from app.main import create_app, lifespan

    app = create_app()
    if native:
        asyncio.run(infer(app, lifespan, control=args.phase == "infer-control"))
    else:
        import uvicorn

        uvicorn.run(
            app, host="127.0.0.1", port=8003, access_log=False, log_level="warning"
        )


if __name__ == "__main__":
    main()
