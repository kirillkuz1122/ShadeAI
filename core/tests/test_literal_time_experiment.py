from pathlib import Path

import pytest

from app.services.notification.extraction import GENERATION_DRAFT
from checks.compare_notification_router import restrict_schema
from checks.literal_time import literal_times, restrict_time_schema


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Доставка ЗАВТРА в 08:15.", ("ЗАВТРА в 08:15",)),
        ("Успеет через 15 минут.", ("через 15 минут",)),
        ("Назначено 21.11.2026.", ("21.11.2026",)),
        ("Ожидается завтра между 13:00 и 16:00.", ("завтра между 13:00 и 16:00",)),
        ("Сегодня вечером, точного времени пока нет.", ("Сегодня вечером",)),
        ("Встреча в 18:12:30", ()),
        ("Статус: заказ отправили.", ()),
        ("Завтра в\n08:00", None),
    ],
)
def test_time_candidates_are_full_source_quotes(text, expected):
    assert literal_times("", text) == expected


def test_matching_repeats_and_excess_candidate_count():
    assert literal_times("Завтра", "Завтра") == ("Завтра",)
    assert literal_times("", ", ".join(f"{i}:00" for i in range(13))) is None


def test_restrict_time_keeps_null_and_preserves_noise_and_original_schema():
    base = GENERATION_DRAFT.json_schema()
    noise = restrict_schema(base, "noise")
    assert restrict_time_schema(noise, ("завтра",)) == noise
    narrowed = restrict_time_schema(base, ("завтра",))
    event = narrowed["$defs"]["EventGenerationDraft"]
    assert event["properties"]["time_expression"] == {"enum": [None, "завтра"]}
    assert narrowed["$defs"]["NoiseGenerationDraft"] == base["$defs"]["NoiseGenerationDraft"]
    assert "enum" not in base["$defs"]["EventGenerationDraft"]["properties"]["time_expression"]


def test_time_literals_cannot_run_as_holdout(tmp_path):
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[1] / "checks/evaluate_extraction.py"
    result = subprocess.run(
        [sys.executable, str(script), "--time-literals", "--stage", "holdout"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2 and "только для native development" in result.stderr
