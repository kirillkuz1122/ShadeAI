import copy
import subprocess
import sys
from pathlib import Path

import pytest

from checks.compare_notification_router import predict, rules_sha256
from checks.diagnose_extraction import select_failed
from checks.evaluation_dataset import load_dataset

CORE = Path(__file__).resolve().parents[1]
DATASET = CORE / "checks/eval-notifications-2026-11-16.json"


def fixture_report(dataset, info):
    rows = [
        {
            "id": case["id"],
            "expected_category": case["expected"]["category"],
            "route": predict(case["title"], case["text"])[0],
            "error": "LLM_BAD_RESPONSE" if index == 1 else None,
        }
        for index, case in enumerate(dataset["cases"])
    ]
    return {
        "dataset_sha256": info["dataset_sha256"],
        "rows": rows,
        "router_rules": {"strategy": "constrain-category-only", "sha256": rules_sha256()},
    }


def test_replay_selects_failed_ids_from_matching_report():
    dataset, info = load_dataset(DATASET, "development")
    reference = fixture_report(dataset, info)
    ids, use_rules = select_failed(dataset, info, reference)
    assert use_rules and ids == {dataset["cases"][1]["id"]}


@pytest.mark.parametrize("bad", ["duplicate", "dataset", "router", "unregistered"])
def test_replay_checks_provenance_before_loading_a_model(bad):
    dataset, info = load_dataset(DATASET, "development")
    reference = fixture_report(dataset, info)
    if bad == "duplicate":
        reference["rows"][1] = copy.copy(reference["rows"][0])
    elif bad == "dataset":
        reference["dataset_sha256"] = "wrong"
    elif bad == "router":
        reference["rows"][0]["route"] = "noise"
    else:
        info["known_development_overlap"] = 0
    with pytest.raises(ValueError):
        select_failed(dataset, info, reference)


def test_existing_diagnostics_are_not_overwritten(tmp_path):
    output = tmp_path / "existing.json"
    output.write_text("original")
    result = subprocess.run(
        [
            sys.executable,
            str(CORE / "checks/diagnose_extraction.py"),
            "--model",
            str(tmp_path / "missing.gguf"),
            "--evaluation",
            str(tmp_path / "missing-report.json"),
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2 and "Выходной отчёт уже существует" in result.stderr
    assert output.read_text() == "original"
