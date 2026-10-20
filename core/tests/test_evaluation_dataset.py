import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from checks.evaluation_dataset import MAX_BYTES, DatasetError, input_signature, load_dataset

CORE = Path(__file__).resolve().parents[1]
SOURCE = CORE / "checks/eval-notifications.json"


def write(tmp_path, data):
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(data, ensure_ascii=False))
    return path


def sample():
    return copy.deepcopy(json.loads(SOURCE.read_text()))


def test_original_development_preflight_and_renamed_reformatted_holdout(tmp_path):
    data, info = load_dataset(SOURCE)
    assert info["cases"] == 40 and info["known_development_overlap"] == 40
    data["version"] = 19
    data["cases"].reverse()
    for i, case in enumerate(data["cases"]):
        case["id"] = f"fresh-{i}"
        case["title"] = "  " + case["title"].upper() + "  "
    with pytest.raises(DatasetError, match="holdout"):
        load_dataset(write(tmp_path, data), "holdout")


def test_unseen_sample_does_not_claim_independence(tmp_path):
    data = sample()
    data["cases"] = [data["cases"][0]]
    data["cases"][0].update(title="Синтетический заказ не из dev", text="Статус подготовки.")
    data["cases"][0]["expected"] = {
        "category": "delivery",
        "priority": "default",
        "time": {"resolution": "absent", "at": None, "date": None},
    }
    _, info = load_dataset(write(tmp_path, data), "holdout")
    assert info["known_development_overlap"] == 0
    assert info["independence"].startswith("not established")


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["cases"].append(copy.deepcopy(d["cases"][0])),
        lambda d: d["cases"][1].update(title=d["cases"][0]["title"], text=d["cases"][0]["text"]),
        lambda d: d.update(cases=[]),
        lambda d: d.update(version=True),
        lambda d: d.update(timezone="Not/A_Zone"),
        lambda d: d.update(timestamp="2026-10-10T10:00:00"),
        lambda d: d["cases"][0]["expected"].update(category="unknown"),
        lambda d: d["cases"][0]["expected"].update(service=[]),
        lambda d: d["cases"][0]["expected"].update(service=["never-in-source"]),
        lambda d: d["cases"][0]["expected"]["time"].update(resolution="exact", at=None),
        lambda d: d["cases"][0]["expected"]["time"].update(
            resolution="date_only", date="2026-02-30"
        ),
        lambda d: d["cases"][-1]["expected"].update(priority="high"),
    ],
)
def test_invalid_annotation_rejected_without_payload_in_error(tmp_path, change):
    data = sample()
    private_title = data["cases"][0]["title"]
    change(data)
    with pytest.raises(DatasetError) as error:
        load_dataset(write(tmp_path, data))
    assert "never-in-source" not in str(error.value)
    assert private_title not in str(error.value)


def test_duplicate_json_fields_and_size_limits(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"private-input": 1, "private-input": 2}')
    with pytest.raises(DatasetError, match="Повторное") as error:
        load_dataset(path)
    assert "private-input" not in str(error.value)
    path.write_bytes(b" " * (MAX_BYTES + 1))
    with pytest.raises(DatasetError, match="размер"):
        load_dataset(path)


def test_fewshot_is_registered_and_case_whitespace_does_not_make_new_input():
    case = {
        "title": "Проверить батарейки",
        "text": "Напоминание: Проверить батарейки завтра в 07:45.",
    }
    registry = json.loads((CORE / "checks/development-inputs.json").read_text())
    assert input_signature(case) in registry["signatures"]
    assert input_signature(case) == input_signature(
        {k: "  " + v.upper() + "  " for k, v in case.items()}
    )


def test_cli_preflight_without_model_and_holdout_failure_before_missing_model(tmp_path):
    script = CORE / "checks/evaluate_extraction.py"
    run = subprocess.run(
        [sys.executable, str(script), "--validate-only"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert run.returncode == 0 and json.loads(run.stdout)["cases"] == 40
    output = tmp_path / "result.json"
    run = subprocess.run(
        [
            sys.executable,
            str(script),
            "--stage",
            "holdout",
            "--model",
            str(tmp_path / "missing.gguf"),
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert run.returncode == 2 and "holdout" in run.stderr
    assert "FileNotFoundError" not in run.stderr and not output.exists()


def test_existing_report_checked_before_resolving_model(tmp_path):
    output = tmp_path / "existing.json"
    output.write_text("preserve")
    run = subprocess.run(
        [
            sys.executable,
            str(CORE / "checks/evaluate_extraction.py"),
            "--model",
            str(tmp_path / "missing.gguf"),
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert run.returncode == 2 and "Файл отчёта уже существует" in run.stderr
    assert output.read_text() == "preserve"


@pytest.mark.parametrize(
    "registry", [{"version": 1, "signatures": []}, {"version": True, "signatures": ["a" * 64]}]
)
def test_bad_registry_fails_closed(tmp_path, monkeypatch, registry):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr("checks.evaluation_dataset.REGISTRY", path)
    with pytest.raises(DatasetError, match="реестр dev"):
        load_dataset(SOURCE, "holdout")


def test_deep_json_is_a_safe_preflight_error(tmp_path):
    path = tmp_path / "deep.json"
    path.write_text("[" * 2000 + "0" + "]" * 2000)
    with pytest.raises(DatasetError):
        load_dataset(path)
