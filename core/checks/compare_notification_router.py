"""TASK-18: сравнение правил с сохранённым native-отчётом, только development."""

import argparse
import hashlib
import json
import re
from collections import Counter
from copy import deepcopy
from pathlib import Path

from checks.evaluation_dataset import DatasetError, load_dataset, unique_object
from checks.extraction_metrics import CATEGORIES

RULES = {
    "delivery": r"\b(?:посылк\w*|курьер\w*|постамат\w*)\b|\bпункт\w* выдач\w*\b",
    "transport": r"\b(?:такси|поездк\w*)\b|\bяндекс go\b",
    "calendar": r"\b(?:встреч[аеиую]|совещани\w*|заседани\w*)\b",
    "reminder": r"\bнапоминани\w*\b|\bне забыть\b",
    "noise": (
        r"\b(?:реклам\w*|скидк\w*|промокод\w*|опрос\w*)\b|"
        r"\b(?:оцените|обновили) приложени\w*\b"
    ),
}
PATTERNS = {label: re.compile(rule) for label, rule in RULES.items()}


def predict(title: str, text: str) -> tuple[str | None, tuple[str, ...]]:
    parts = [" ".join(value.casefold().replace("ё", "е").split()) for value in (title, text)]
    labels = tuple(
        label for label, pattern in PATTERNS.items() if any(pattern.search(part) for part in parts)
    )
    return (labels[0] if len(labels) == 1 else None), labels


def rules_sha256():
    return hashlib.sha256(json.dumps(RULES, sort_keys=True).encode()).hexdigest()


def restrict_schema(schema: dict, category: str) -> dict:
    if category not in CATEGORIES:
        raise ValueError("Неизвестная категория маршрутизатора")
    branch = "NoiseGenerationDraft" if category == "noise" else "EventGenerationDraft"
    selected = deepcopy(schema["$defs"][branch])
    selected["properties"]["category"] = {"type": "string", "const": category}
    return selected


def compare(dataset, info, reference):
    if not isinstance(reference, dict) or reference.get("dataset_sha256") != info["dataset_sha256"]:
        raise ValueError("Хеш набора не совпадает с отчётом Qwen")
    cases = dataset["cases"]
    expected = {case["id"]: case["expected"]["category"] for case in cases}
    reference_rows = reference.get("rows")
    if not isinstance(reference_rows, list) or len(reference_rows) != len(cases):
        raise ValueError("Отчёт Qwen не покрывает набор целиком")
    qwen = {}
    for row in reference_rows:
        if not isinstance(row, dict):
            raise ValueError("Неверная строка отчёта Qwen")
        case_id = row.get("id")
        label = row.get("predicted_category")
        if (
            not isinstance(case_id, str)
            or case_id not in expected
            or case_id in qwen
            or expected[case_id] != row.get("expected_category")
            or "predicted_category" not in row
            or label not in (*CATEGORIES, None)
        ):
            raise ValueError("Невозможно связать отчёт Qwen с разметкой")
        qwen[case_id] = label

    rows = []
    for case in cases:
        case_id = case["id"]
        rule, matches = predict(case["title"], case["text"])
        rows.append(
            {
                "id": case_id,
                "expected": expected[case_id],
                "rule": rule,
                "signals": matches,
                "qwen": qwen[case_id],
                "rule_or_saved_qwen": rule or qwen[case_id],
            }
        )
    answered = [r for r in rows if r["rule"] is not None]
    correct = sum(r["rule"] == r["expected"] for r in answered)
    improved = [r["id"] for r in answered if r["rule"] == r["expected"] != r["qwen"]]
    regressed = [r["id"] for r in answered if r["rule"] != r["expected"] == r["qwen"]]
    return {
        "stage": "development",
        "dataset_sha256": info["dataset_sha256"],
        "registered_development_inputs": info["known_development_overlap"],
        "rules_sha256": rules_sha256(),
        "total": len(rows),
        "rules_answered": len(answered),
        "rules_correct": correct,
        "abstained": len(rows) - len(answered),
        "abstention_reasons": dict(
            Counter(
                "conflicting_signals" if r["signals"] else "no_signal"
                for r in rows
                if r["rule"] is None
            )
        ),
        "qwen_category_correct": sum(r["qwen"] == r["expected"] for r in rows),
        "simulation_category_correct": sum(r["rule_or_saved_qwen"] == r["expected"] for r in rows),
        "simulation_improved_ids": improved,
        "simulation_regressed_ids": regressed,
        "noise_false_drop_ids_if_skipped": [
            r["id"] for r in answered if r["rule"] == "noise" and r["expected"] != "noise"
        ],
        "per_class": {
            label: {
                "total": sum(r["expected"] == label for r in rows),
                "rules_correct": sum(r["rule"] == r["expected"] == label for r in rows),
                "qwen_correct": sum(r["qwen"] == r["expected"] == label for r in rows),
            }
            for label in CATEGORIES
        },
        "limitations": (
            "category only; simulation, no inference, no routing, no extraction, no skip"
        ),
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        dataset, info = load_dataset(args.dataset, "development")
        if info["known_development_overlap"] != info["cases"]:
            raise ValueError("Сравнивать можно только уже зарегистрированные dev-входы")
        with args.reference.open("rb") as stream:
            raw = stream.read(2**20 + 1)
        if len(raw) > 2**20:
            raise ValueError("Слишком большой отчёт Qwen")
        ref = json.loads(raw, object_pairs_hook=unique_object)
        report = compare(dataset, info, ref)
        report["reference_sha256"] = hashlib.sha256(raw).hexdigest()
        with args.output.open("x") as output:
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.write("\n")
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        parser.error("Не удалось прочитать отчёт Qwen")
    except (DatasetError, ValueError) as error:
        parser.error(str(error))
    except OSError:
        parser.error("Отчёт недоступен или выходной файл уже существует")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
