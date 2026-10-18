"""TASK-18: фиксированный синтетический набор, без настройки промпта по его ответам."""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import platform
import secrets
import sys
import tempfile
import time
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(CORE), str(CORE / "checks")]
from extraction_metrics import score, summarize  # noqa: E402


async def evaluate(model, dataset, threads):
    from app.schemas import NotificationIn
    from app.services.llm.engine import EngineConfig, LLMError, LocalLLMEngine
    from app.services.notification.extraction import (
        EXAMPLES,
        PROMPT,
        ExtractionDraft,
        LLMNotificationProcessor,
    )

    engine = LocalLLMEngine(EngineConfig(True, str(model), 2048, threads, 256, 2304, 180, 90))
    processor = LLMNotificationProcessor(engine, dataset["timezone"])
    report = {
        "platform": "development-computer",
        "python": platform.python_version(),
        "machine": platform.machine(),
        "kernel": platform.release(),
        "llama_cpp_python": importlib.metadata.version("llama-cpp-python"),
        "prompt_sha256": hashlib.sha256(
            json.dumps(
                [{"role": "system", "content": PROMPT}, *EXAMPLES],
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest(),
        "dataset_version": dataset["version"],
        "schema_sha256": hashlib.sha256(
            json.dumps(
                ExtractionDraft.model_json_schema(),
                sort_keys=True,
            ).encode()
        ).hexdigest(),
        "temperature": 0.0,
        "seed": 42,
        "threads": threads,
        "context": 2048,
        "max_tokens": 256,
        "memory_limit_mb": 2304,
        "annotation": "synthetic-by-agent; requires-human-review",
        "rows": [],
    }
    completions = []
    original = engine.generate

    async def record(*args, **kwargs):
        result = await original(*args, **kwargs)
        completions.append(result.model_dump(exclude={"content"}))
        return result

    engine.generate = record
    try:
        try:
            report["load"] = (await engine.load()).model_dump()
            # Прогрев взят из dev, не из измеряемого набора.
            await processor(
                NotificationIn(
                    app_name="ru.ozon.app.android",
                    title="Курьер",
                    text="Курьер прибудет через 15 минут",
                    timestamp=dataset["timestamp"],
                )
            )
            report["warmup"] = "ok"
        except LLMError as error:
            report["warmup"] = error.code
        completions.clear()
        for case in dataset["cases"]:
            notification = NotificationIn(
                **{key: case[key] for key in ("app_name", "title", "text")},
                timestamp=dataset["timestamp"],
            )
            started = time.monotonic()
            result, error = None, None
            try:
                result = (await processor(notification)).model_dump()
            except LLMError as exc:
                error = exc.code
            fields = score(case["expected"], result)
            report["rows"].append(
                {
                    "id": case["id"],
                    "expected_category": case["expected"]["category"],
                    "predicted_category": result["category"] if result else None,
                    "result": result,
                    "error": error,
                    "fields": fields,
                    "exact_match": all(fields.values()),
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                }
            )
            print(
                json.dumps({"id": case["id"], "exact": all(fields.values()), "error": error}),
                flush=True,
            )
    finally:
        await engine.close()
    report["completions"] = completions
    report["peak_rss_bytes"] = max(
        [report.get("load", {}).get("peak_rss_bytes", 0)]
        + [completion["peak_rss_bytes"] for completion in completions]
    )
    report["summary"] = summarize(report["rows"])
    report["hardware_acceptance"] = "not-performed; development CPU does not establish Pi goals"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--threads", type=int, choices=(2, 4), default=2)
    parser.add_argument("--dataset", type=Path, default=CORE / "checks/eval-notifications.json")
    args = parser.parse_args()
    model, output = args.model.resolve(strict=True), args.output.resolve()
    dataset_raw = args.dataset.read_bytes()
    dataset = json.loads(dataset_raw)
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="task18-eval-", dir=CORE / ".pytest_cache") as scratch:
        os.chdir(scratch)
        os.environ["SHADE_API_KEY"] = secrets.token_urlsafe(32)
        try:
            report = asyncio.run(evaluate(model, dataset, args.threads))
        finally:
            os.chdir(previous)
    report["dataset_sha256"] = hashlib.sha256(dataset_raw).hexdigest()
    if Path("/proc/cpuinfo").is_file():
        report["cpu"] = next(
            (
                line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")
            ),
            "unknown",
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if not (
        report["summary"]["courier_reminder"]["sample_target_90_percent"]
        and report["summary"]["processor_ms"]["sample_target_4_seconds"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
