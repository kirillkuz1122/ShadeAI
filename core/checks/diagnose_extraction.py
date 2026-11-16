"""Повтор отказов на зарегистрированных dev-примерах, без сохранения сырых ответов."""

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))

from checks.compare_notification_router import predict, restrict_schema, rules_sha256  # noqa: E402
from checks.evaluation_dataset import load_dataset, unique_object  # noqa: E402
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


def select_failed(dataset, info, report):
    if info["known_development_overlap"] != info["cases"]:
        raise ValueError("Диагностика требует зарегистрированные dev-входы")
    if report.get("dataset_sha256") != info["dataset_sha256"]:
        raise ValueError("Отчёт относится к другому набору")
    route = report.get("router_rules")
    if route is not None and route != {
        "strategy": "constrain-category-only",
        "sha256": rules_sha256(),
    }:
        raise ValueError("Версия правил в отчёте отличается")
    time_mode = report.get("time_literals")
    if time_mode is not None and time_mode != {
        "strategy": "source-span-enum",
        "sha256": literal_time_sha256(),
    }:
        raise ValueError("Версия фрагментов времени в отчёте отличается")
    service_mode = report.get("service_literals")
    if service_mode is not None and service_mode != {
        "strategy": "named-service-enum",
        "sha256": literal_service_sha256(),
    }:
        raise ValueError("Версия списка сервисов отличается")
    cases = {item["id"]: item for item in dataset["cases"]}
    rows = report["rows"]
    ids = [row["id"] for row in rows]
    if len(ids) != len(cases) or set(ids) != set(cases):
        raise ValueError("Отчёт не покрывает набор целиком")
    for row in rows:
        case = cases[row["id"]]
        if row.get("expected_category") != case["expected"]["category"]:
            raise ValueError("Отчёт не совпадает с разметкой")
        if route is not None and (
            "route" not in row or row["route"] != predict(case["title"], case["text"])[0]
        ):
            raise ValueError("Решение маршрутизатора отличается")
        if time_mode is not None:
            candidates = literal_times(case["title"], case["text"])
            count = len(candidates) if candidates is not None else None
            if "time_candidate_count" not in row or row["time_candidate_count"] != count:
                raise ValueError("Кандидаты времени отличаются")
        if service_mode is not None:
            services = literal_services(case["title"], case["text"])
            count = len(services) if services is not None else None
            if "service_candidate_count" not in row or row["service_candidate_count"] != count:
                raise ValueError("Кандидаты сервиса отличаются")
    return {row["id"] for row in rows if row.get("error") == "LLM_BAD_RESPONSE"}, bool(route)


async def diagnose(
    model,
    dataset,
    ids,
    *,
    router_rules=False,
    time_literals=False,
    service_literals=False,
    expected_model=None,
):
    from pydantic import ValidationError

    from app.schemas import NotificationIn
    from app.services.llm.engine import EngineConfig, LLMError, LocalLLMEngine
    from app.services.notification.extraction import (
        EXAMPLES,
        GENERATION_DRAFT,
        PROMPT,
        ExtractionDraft,
        parse_extraction,
    )

    engine = LocalLLMEngine(EngineConfig(True, str(model), 2048, 2, 256, 2304, 180, 90))
    output = []
    try:
        loaded = await engine.load()
        if expected_model is not None and expected_model != loaded.sha256:
            raise ValueError("Другая версия модели")
        for case in dataset["cases"]:
            if case["id"] not in ids:
                continue
            notification = NotificationIn(
                **{key: case[key] for key in ("app_name", "title", "text")},
                timestamp=dataset["timestamp"],
            )
            item = {"id": case["id"], "fields": {}}
            schema = GENERATION_DRAFT.json_schema()
            if router_rules:
                route, _ = predict(notification.title, notification.text)
                if route is not None:
                    schema = restrict_schema(schema, route)
                item["route"] = route
            if time_literals:
                candidates = literal_times(notification.title, notification.text)
                if candidates is not None:
                    schema = restrict_time_schema(schema, candidates)
                item["time_candidate_count"] = len(candidates) if candidates is not None else None
            if service_literals:
                services = literal_services(notification.title, notification.text)
                if services is not None:
                    schema = restrict_service_schema(schema, services)
                item["service_candidate_count"] = len(services) if services is not None else None
            try:
                result = await engine.generate(
                    [
                        {"role": "system", "content": PROMPT},
                        *EXAMPLES,
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "title": notification.title,
                                    "text": notification.text,
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    schema=schema,
                )
                item["finish_reason"] = result.finish_reason
                try:
                    if result.finish_reason != "stop":
                        raise ValueError("Обрезанный вывод")
                    parse_extraction(result.content, notification, dataset["timezone"])
                except (ValueError, RecursionError, OverflowError):
                    item["reproduced"] = True
                else:
                    item["reproduced"] = False
                draft = ExtractionDraft.model_validate(
                    json.loads(
                        result.content,
                        object_pairs_hook=unique_object,
                    )
                )
                for field in ("subject", "location", "service", "time_expression"):
                    value = getattr(draft, field)
                    if value is None:
                        kind = "null"
                    elif not value.strip() or any(ord(char) < 32 for char in value):
                        kind = "blank_or_control"
                    elif value in notification.title or value in notification.text:
                        kind = "literal"
                    elif any(
                        value.casefold() in text.casefold()
                        for text in (notification.title, notification.text)
                    ):
                        kind = "case_only"
                    else:
                        kind = "not_literal"
                    item["fields"][field] = kind
            except ValidationError as exc:
                allowed = {
                    "category",
                    "priority",
                    "subject",
                    "location",
                    "service",
                    "time_expression",
                }
                item["schema_fields"] = sorted(
                    {
                        str(error["loc"][0]) if error["loc"] and error["loc"][0] in allowed else "_"
                        for error in exc.errors(include_input=False)
                    }
                )
            except (ValueError, RecursionError):
                item["error"] = "INVALID_JSON"
            except LLMError as exc:
                item["error"] = exc.code
            output.append(item)
    finally:
        await engine.close()
    return output, loaded.sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--evaluation", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--dataset", type=Path, default=CORE / "checks/eval-notifications.json")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("Выходной отчёт уже существует")
    try:
        dataset, info = load_dataset(args.dataset, "development")
        with args.evaluation.open("rb") as stream:
            raw = stream.read(2**20 + 1)
        if len(raw) > 2**20:
            raise ValueError("Слишком большой отчёт")
        evaluation = json.loads(raw, object_pairs_hook=unique_object)
        ids, router_rules = select_failed(dataset, info, evaluation)
        if not ids:
            raise ValueError("Нет отказов LLM_BAD_RESPONSE для повтора")
        expected_model = evaluation["load"]["sha256"]
        time_literals = evaluation.get("time_literals") is not None
        service_literals = evaluation.get("service_literals") is not None
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OSError):
        parser.error("Несовместимый dev-набор или отчёт с отказами")
    model = args.model.resolve(strict=True)
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="task18-dev-", dir=CORE / ".pytest_cache") as scratch:
        os.chdir(scratch)
        os.environ["SHADE_API_KEY"] = secrets.token_urlsafe(32)
        try:
            rows, model_hash = asyncio.run(
                diagnose(
                    model,
                    dataset,
                    ids,
                    router_rules=router_rules,
                    time_literals=time_literals,
                    service_literals=service_literals,
                    expected_model=expected_model,
                )
            )
        finally:
            os.chdir(previous)
    report = {
        "stage": "development-replay-of-failed-subset",
        "dataset_sha256": info["dataset_sha256"],
        "evaluation_sha256": hashlib.sha256(raw).hexdigest(),
        "model_sha256": model_hash,
        "router_rules": router_rules,
        "time_literals": time_literals,
        "service_literals": service_literals,
        "raw_answers_saved": False,
        "rows": rows,
    }
    with output.open("x") as destination:
        destination.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
