import json
from collections import Counter
from pathlib import Path

import pytest

from checks.extraction_metrics import score, summarize, wilson


def test_failed_outputs_count_in_denominators_and_classification_errors():
    rows = []
    for expected, actual in (
        ("delivery", "delivery"),
        ("delivery", None),
        ("reminder", "delivery"),
        ("reminder", "reminder"),
    ):
        correct = expected == actual
        rows.append(
            {
                "expected_category": expected,
                "predicted_category": actual,
                "result": {} if actual else None,
                "fields": {"category": correct},
                "exact_match": correct,
                "elapsed_ms": 5000 if actual is None else 1000,
            }
        )
    result = summarize(rows)
    assert result["valid"] == 3 and result["classification_accuracy"] == 0.5
    assert result["courier_reminder"]["correct"] == 2
    assert result["courier_reminder"]["total"] == 4
    assert result["courier_reminder"]["sample_target_90_percent"] is False
    assert result["per_class"]["delivery"]["precision"] == 0.5
    assert result["per_class"]["delivery"]["recall"] == 0.5
    assert result["per_class"]["reminder"]["precision"] == 1
    assert result["per_class"]["reminder"]["recall"] == 0.5
    assert result["processor_ms"] == {
        "p50": 1000,
        "p95": 5000,
        "max": 5000,
        "sample_target_4_seconds": False,
    }


def test_field_scoring_and_coverage_do_not_make_unlabelled_fields_correct():
    expected = {
        "category": "delivery",
        "priority": "default",
        "service": ["Ozon"],
        "location": [None],
        "time": {"resolution": "date_only", "at": None, "date": "2026-10-11"},
    }
    actual = {
        "category": "delivery",
        "priority": "default",
        "entities": {"subject": "Любое название", "service": "  OZON ", "location": None},
        "time": {"resolution": "date_only", "at": None, "date": "2026-10-11"},
    }
    fields = score(expected, actual)
    assert all(fields.values()) and "subject" not in fields
    assert not any(score(expected, None).values())
    actual["time"]["date"] = "2026-10-12"
    assert score(expected, actual)["time.date"] is False


def test_small_perfect_sample_does_not_prove_population_accuracy_90():
    lower, upper = wilson(20, 20)
    assert lower == pytest.approx(0.8389) and upper == 1
    assert wilson(0, 0) is None
    assert wilson(0, 20)[1] == pytest.approx(0.1611)


def test_dataset_has_fixed_balance_ids_and_explicit_partial_annotation():
    source = Path(__file__).resolve().parents[1] / "checks/eval-notifications.json"
    dataset = json.loads(source.read_text())
    cases = dataset["cases"]
    assert len({case["id"] for case in cases}) == len(cases) == 40
    assert Counter(case["expected"]["category"] for case in cases) == {
        "delivery": 10,
        "transport": 5,
        "calendar": 10,
        "reminder": 10,
        "noise": 5,
    }
    assert all(set(case["expected"]["time"]) == {"resolution", "at", "date"} for case in cases)
    assert all(
        "subject" in case["expected"]
        for case in cases
        if case["expected"]["category"] == "reminder"
    )
