"""Разбор ошибок уже просмотренного синтетического eval-v1 (теперь dev), без raw-ответов."""

import argparse
import asyncio
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))


async def diagnose(model, dataset, ids):
    from pydantic import ValidationError

    from app.schemas import NotificationIn
    from app.services.llm.engine import EngineConfig, LLMError, LocalLLMEngine
    from app.services.notification.extraction import (
        EXAMPLES,
        PROMPT,
        ExtractionDraft,
        unique_object,
    )

    engine = LocalLLMEngine(EngineConfig(True, str(model), 2048, 2, 256, 2304, 180, 90))
    output = []
    try:
        await engine.load()
        for case in dataset["cases"]:
            if case["id"] not in ids:
                continue
            notification = NotificationIn(
                **{key: case[key] for key in ("app_name", "title", "text")},
                timestamp=dataset["timestamp"],
            )
            item = {"id": case["id"], "fields": {}}
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
                    schema=ExtractionDraft.model_json_schema(),
                )
                item["finish_reason"] = result.finish_reason
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
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--evaluation", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    model, output = args.model.resolve(strict=True), args.output.resolve()
    evaluation = json.loads(args.evaluation.read_text())
    ids = {row["id"] for row in evaluation["rows"] if row["error"] == "LLM_BAD_RESPONSE"}
    dataset = json.loads((CORE / "checks/eval-notifications.json").read_text())
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="task18-dev-", dir=CORE / ".pytest_cache") as scratch:
        os.chdir(scratch)
        os.environ["SHADE_API_KEY"] = secrets.token_urlsafe(32)
        try:
            rows = asyncio.run(diagnose(model, dataset, ids))
        finally:
            os.chdir(previous)
    report = {"stage": "seen-eval-v1-is-now-dev", "raw_answers_saved": False, "rows": rows}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
