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

from checks.compare_notification_router import predict, restrict_schema, rules_sha256  # noqa: E402
from checks.evaluation_dataset import DatasetError, load_dataset  # noqa: E402
from checks.literal_service import (  # noqa: E402
    literal_service_sha256,
    literal_services,
    restrict_service_schema,
)
from checks.literal_time import (  # noqa: E402
    literal_time_sha256,
    literal_times,
    restrict_time_schema,
)


async def evaluate(
    model, dataset, threads, *, router_rules=False, time_literals=False, service_literals=False
):
    from app.schemas import NotificationIn
    from app.services.llm.engine import EngineConfig, LLMError, LocalLLMEngine
    from app.services.notification.extraction import (
        EXAMPLES,
        GENERATION_DRAFT,
        PROMPT,
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
                GENERATION_DRAFT.json_schema(),
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
    route = None
    candidates = None
    services = None
    if service_literals:
        report["service_literals"] = {
            "strategy": "named-service-enum",
            "sha256": literal_service_sha256(),
        }
    if time_literals:
        report["time_literals"] = {"strategy": "source-span-enum", "sha256": literal_time_sha256()}
    if router_rules:
        report["router_rules"] = {"strategy": "constrain-category-only", "sha256": rules_sha256()}

    async def record(*args, **kwargs):
        if route is not None:
            kwargs["schema"] = restrict_schema(kwargs["schema"], route)
        if candidates is not None:
            kwargs["schema"] = restrict_time_schema(kwargs["schema"], candidates)
        if services is not None:
            kwargs["schema"] = restrict_service_schema(kwargs["schema"], services)
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
            if router_rules:
                route, _ = predict(notification.title, notification.text)
            if time_literals:
                candidates = literal_times(notification.title, notification.text)
            if service_literals:
                services = literal_services(notification.title, notification.text)
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
                    **({"route": route} if router_rules else {}),
                    **(
                        {
                            "time_candidate_count": len(candidates)
                            if candidates is not None
                            else None
                        }
                        if time_literals
                        else {}
                    ),
                    **(
                        {"service_candidate_count": len(services) if services is not None else None}
                        if service_literals
                        else {}
                    ),
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
    parser.add_argument("--model", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--router-rules", action="store_true", help="QA: сузить категорию на dev")
    parser.add_argument(
        "--time-literals", action="store_true", help="QA: перечислить цитаты времени"
    )
    parser.add_argument("--service-literals", action="store_true", help="QA: цитаты имён сервисов")
    parser.add_argument("--threads", type=int, choices=(2, 4), default=2)
    parser.add_argument("--dataset", type=Path, default=CORE / "checks/eval-notifications.json")
    parser.add_argument("--stage", choices=("development", "holdout"), default="development")
    args = parser.parse_args()
    if args.router_rules and (args.validate_only or args.stage != "development"):
        parser.error("--router-rules доступен только для native development")
    if args.time_literals and (args.validate_only or args.stage != "development"):
        parser.error("--time-literals доступен только для native development")
    if args.service_literals and (args.validate_only or args.stage != "development"):
        parser.error("--service-literals доступен только для native development")
    try:
        dataset, dataset_info = load_dataset(args.dataset, args.stage)
    except DatasetError as error:
        parser.error(str(error))
    if args.router_rules and dataset_info["known_development_overlap"] != dataset_info["cases"]:
        parser.error("--router-rules требует заранее зарегистрированные dev-входы")
    if args.time_literals and dataset_info["known_development_overlap"] != dataset_info["cases"]:
        parser.error("--time-literals требует заранее зарегистрированные dev-входы")
    if args.service_literals and dataset_info["known_development_overlap"] != dataset_info["cases"]:
        parser.error("--service-literals требует заранее зарегистрированные dev-входы")
    if args.validate_only:
        if args.model is not None or args.output is not None:
            parser.error("--validate-only не принимает --model/--output")
        print(json.dumps(dataset_info, ensure_ascii=False))
        return
    if args.model is None or args.output is None:
        parser.error("Для native-оценки нужны --model и --output")
    output = args.output.resolve()
    if output.exists():
        parser.error("Файл отчёта уже существует; выберите новый --output")
    model = args.model.resolve(strict=True)
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="task18-eval-", dir=CORE / ".pytest_cache") as scratch:
        os.chdir(scratch)
        os.environ["SHADE_API_KEY"] = secrets.token_urlsafe(32)
        try:
            report = asyncio.run(
                evaluate(
                    model,
                    dataset,
                    args.threads,
                    router_rules=args.router_rules,
                    time_literals=args.time_literals,
                    service_literals=args.service_literals,
                )
            )
        finally:
            os.chdir(previous)
    report["stage"] = args.stage
    report["dataset_preflight"] = dataset_info
    report["dataset_sha256"] = dataset_info["dataset_sha256"]
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
    with output.open("x") as destination:
        destination.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if not (
        report["summary"]["courier_reminder"]["sample_target_90_percent"]
        and report["summary"]["processor_ms"]["sample_target_4_seconds"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
