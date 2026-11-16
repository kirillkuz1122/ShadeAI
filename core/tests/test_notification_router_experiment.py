import copy
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.notification.extraction import GENERATION_DRAFT
from checks.compare_notification_router import compare, predict, restrict_schema
from checks.evaluation_dataset import DatasetError, load_dataset

CORE = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("title", "text", "category", "signals"),
    [
        ("ТАКСИ\u00a0ждёт", "Машина у дома", "transport", ("transport",)),
        ("Пункт выдачи", "Посылку можно забрать", "delivery", ("delivery",)),
        ("Скидка на такси", "Реклама", None, ("transport", "noise")),
        ("Курьер", "Встречайте у входа", "delivery", ("delivery",)),
        ("Порядок", "Статус обновлён", None, ()),
        ("Напоминание", "Забрать посылку", None, ("delivery", "reminder")),
    ],
)
def test_unambiguous_markers_and_conflicts(title, text, category, signals):
    assert predict(title, text) == (category, signals)


def test_schema_restriction_keeps_event_fields_and_does_not_mutate_base():
    base = GENERATION_DRAFT.json_schema()
    before = copy.deepcopy(base)
    event = restrict_schema(base, "transport")
    noise = restrict_schema(base, "noise")
    assert event["properties"]["category"]["const"] == "transport"
    assert noise["properties"]["category"]["const"] == "noise"
    assert noise["properties"]["time_expression"]["type"] == "null"
    assert event["required"] == base["$defs"]["EventGenerationDraft"]["required"]
    assert (
        event["properties"]["service"]
        == base["$defs"]["EventGenerationDraft"]["properties"]["service"]
    )
    assert base == before


def test_compare_counts_abstentions_and_refuses_duplicates():
    dataset = {
        "cases": [
            {"id": "1", "title": "Такси", "text": "", "expected": {"category": "transport"}},
            {"id": "2", "title": "Статус", "text": "", "expected": {"category": "delivery"}},
        ]
    }
    info = {"dataset_sha256": "test", "known_development_overlap": 2}
    ref = {
        "dataset_sha256": "test",
        "rows": [
            {"id": "1", "expected_category": "transport", "predicted_category": None},
            {"id": "2", "expected_category": "delivery", "predicted_category": "delivery"},
        ],
    }
    result = compare(dataset, info, ref)
    assert (
        result["rules_correct"],
        result["abstained"],
        result["simulation_category_correct"],
    ) == (1, 1, 2)
    ref["rows"][1] = ref["rows"][0]
    with pytest.raises(ValueError, match="разметкой"):
        compare(dataset, info, ref)


def test_reviewed_v2_is_no_longer_valid_as_holdout():
    with pytest.raises(DatasetError, match="holdout"):
        load_dataset(CORE / "checks/eval-notifications-2026-11-16.json", "holdout")


def test_router_native_cannot_be_enabled_for_holdout(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(CORE / "checks/evaluate_extraction.py"),
            "--router-rules",
            "--stage",
            "holdout",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2 and "только для native development" in result.stderr
