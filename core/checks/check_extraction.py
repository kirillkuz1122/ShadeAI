"""Синтетика: настоящий GGUF → worker → SQLite → API → рестарт, без устройств/рабочей БД."""

import argparse
import asyncio
import hashlib
import json
import os
import platform
import secrets
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))
CASES = json.loads((CORE / "checks/extraction-smoke.json").read_text())


async def scenario(expected_load_error=None):
    import httpx

    from app import main
    from app.services.ha_bridge.client import HAClient
    from app.services.llm.engine import LocalLLMEngine

    commands, completions, engines = [], [], []

    class SyntheticHA(HAClient):
        def __init__(self):
            super().__init__()
            self.old = self._client

            def handle(request):
                if request.method == "POST":
                    commands.append(request.url.path)
                    return httpx.Response(500)
                return httpx.Response(200, json={"message": "API running."})

            self._client = httpx.AsyncClient(
                transport=httpx.MockTransport(handle),
                base_url="http://ha.synthetic",
                trust_env=False,
            )

        async def close(self):
            await self.old.aclose()
            await super().close()

    class RecordingEngine(LocalLLMEngine):
        def __init__(self):
            super().__init__()
            engines.append(self)

        async def generate(self, messages, *, schema=None):
            result = await super().generate(messages, schema=schema)
            completions.append(result.model_dump(exclude={"content"}))
            return result

    main.HAClient, main.LocalLLMEngine = SyntheticHA, RecordingEngine
    report = {
        "platform": "development-computer",
        "python": platform.python_version(),
        "cases": [],
        "dataset_sha256": hashlib.sha256(
            (CORE / "checks/extraction-smoke.json").read_bytes()
        ).hexdigest(),
    }
    headers = {"Authorization": "Bearer " + os.environ["SHADE_API_KEY"]}
    payloads = []
    app = main.create_app()
    async with (
        main.lifespan(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://synthetic",
            headers=headers,
        ) as client,
    ):
        async with asyncio.timeout(200):
            while app.state.llm.status in {"loading", "not_loaded"}:
                await asyncio.sleep(0.02)
        if expected_load_error:
            assert app.state.llm.status == expected_load_error, app.state.llm.status
            async with asyncio.timeout(3):
                while app.state.notification_worker.status != "model_unavailable":
                    await asyncio.sleep(0.01)
            for case in CASES:
                payload = {key: case[key] for key in ("app_name", "title", "text")}
                payload.update(timestamp="2026-10-17T20:50:00Z", event_id=str(uuid4()))
                response = await client.post("/api/v1/notifications", json=payload)
                assert response.status_code == 201
            await asyncio.sleep(0.05)
            rows = (await client.get("/api/v1/notifications")).json()["items"]
            assert len(rows) == len(CASES)
            assert all(
                row["processing_status"] == "pending" and row["processing_attempts"] == 0
                for row in rows
            )
            assert not commands and not completions
            report.update(
                fallback="PASS", error=expected_load_error, pending=len(rows), ha_commands=0
            )
            return report
        assert app.state.llm.status == "ready", app.state.llm.status
        report["load"] = app.state.llm.info.model_dump()
        for case in CASES:
            payload = {key: case[key] for key in ("app_name", "title", "text")}
            payload.update(timestamp="2026-10-17T20:50:00Z", event_id=str(uuid4()))
            started = time.monotonic()
            receipt = await client.post("/api/v1/notifications", json=payload)
            assert receipt.status_code == 201
            assert time.monotonic() - started < 1
            assert receipt.json()["processed_data"] is None
            row_id = receipt.json()["id"]
            payloads.append((payload, row_id))
            async with asyncio.timeout(120):
                while True:
                    row = (await client.get(f"/api/v1/notifications/{row_id}")).json()
                    assert (await client.get("/api/v1/health")).status_code == 200
                    if row["processing_status"] in {"processed", "failed"}:
                        break
                    await asyncio.sleep(0.02)
            result = row["processed_data"]
            correct = bool(
                result
                and result["category"] == case["category"]
                and result["time"]["at"] == case["at"]
            )
            entity_checks = {
                field: result is not None and result["entities"][field] in expected
                for field, expected in case["entities"].items()
            }
            if result:
                assert result["action_authorized"] is False
                assert result["llm"] is True
            report["cases"].append(
                {
                    "id": case["id"],
                    "correct_category_and_time": correct,
                    "entity_checks": entity_checks,
                    "correct": correct and all(entity_checks.values()),
                    "status": row["processing_status"],
                    "error": row["processing_error_code"],
                    "result": result,
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                }
            )
        report["completions"] = completions.copy()
    assert all(engine.process is None for engine in engines)
    count = len(completions)
    # Тот же durable store, новый lifespan/движок: terminal записи не пересчитываются.
    app = main.create_app()
    async with (
        main.lifespan(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://synthetic",
            headers=headers,
        ) as client,
    ):
        async with asyncio.timeout(200):
            while app.state.llm.status in {"loading", "not_loaded"}:
                await asyncio.sleep(0.02)
        assert app.state.llm.status == "ready"
        for (payload, row_id), previous in zip(payloads, report["cases"], strict=True):
            duplicate = await client.post("/api/v1/notifications", json=payload)
            assert duplicate.status_code == 200 and duplicate.json()["status"] == "duplicate"
            row = (await client.get(f"/api/v1/notifications/{row_id}")).json()
            assert row["processed_data"] == previous["result"]
            assert row["processing_status"] == previous["status"]
            assert row["processing_attempts"] == 1
        await asyncio.sleep(0.1)
    assert len(completions) == count and not commands
    assert all(engine.process is None for engine in engines)
    report.update(restart_and_receipts="PASS", ha_commands=0)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-load-error")
    args = parser.parse_args()
    model, output = args.model.resolve(strict=True), args.output.resolve()
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="task17-core-", dir=CORE / ".pytest_cache") as folder:
        os.chdir(folder)
        os.environ.update(
            {
                "SHADE_API_KEY": secrets.token_urlsafe(32),
                "DB_URL": "sqlite+aiosqlite:///./check.db",
                "LOG_DIR": "./logs",
                "HA_BASE_URL": "http://ha.synthetic",
                "HA_TOKEN": "synthetic",
                "HA_TELEMETRY_ENTITIES": "[]",
                "LLM_ENABLED": "true",
                "LLM_MODEL_PATH": str(model),
                "LLM_CONTEXT_SIZE": "2048",
                "LLM_THREADS": "2",
                "LLM_MAX_TOKENS": "256",
                "LLM_LOAD_TIMEOUT_SECONDS": "180",
                "LLM_INFERENCE_TIMEOUT_SECONDS": "90",
                "LLM_MEMORY_LIMIT_MB": "2304",
                "NOTIFICATION_PROCESSOR": "llm",
                "NOTIFICATION_PROCESSING_TIMEOUT_SECONDS": "90",
                "NOTIFICATION_TIMEZONE": "Asia/Yekaterinburg",
                "NOTIFICATION_ALLOWED_APPS": json.dumps(
                    sorted({case["app_name"] for case in CASES})
                ),
            }
        )
        try:
            report = asyncio.run(scenario(args.expected_load_error))
        finally:
            os.chdir(previous)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if args.expected_load_error:
        print(
            json.dumps(
                {
                    "fallback": report["fallback"],
                    "error": report["error"],
                    "pending": report["pending"],
                }
            )
        )
        return
    passed = sum(case["correct"] for case in report["cases"])
    print(
        json.dumps(
            {"correct": passed, "total": len(CASES), "restart": report["restart_and_receipts"]}
        )
    )
    if passed != len(CASES):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
