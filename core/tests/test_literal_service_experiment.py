import subprocess
import sys
from pathlib import Path

import pytest

from app.services.notification.extraction import GENERATION_DRAFT
from checks.compare_notification_router import restrict_schema
from checks.literal_service import literal_services, restrict_service_schema
from checks.literal_time import restrict_time_schema


@pytest.mark.parametrize(
    ("title", "text", "expected"),
    [
        ("OZON", "Заказ OZON и Яндекс Go.", ("OZON", "Яндекс Go")),
        ("wildberries", "Заказ из магазина.", ("wildberries",)),
        ("Заказ подготовлен", "Доставка скоро.", ()),
        ("myOzonAddon", "Курьер из Доставкин.", ()),
    ],
)
def test_service_requires_word_boundaries_and_uses_original_case(title, text, expected):
    assert literal_services(title, text) == expected


def test_service_schema_composes_with_category_and_time_and_keeps_null():
    base = GENERATION_DRAFT.json_schema()
    candidate = restrict_service_schema(
        restrict_time_schema(restrict_schema(base, "delivery"), ("завтра",)), ("OZON",)
    )
    props = candidate["properties"]
    assert props["category"]["const"] == "delivery"
    assert props["time_expression"]["enum"] == [None, "завтра"]
    assert props["service"]["enum"] == [None, "OZON"]
    noise = restrict_schema(base, "noise")
    assert restrict_service_schema(noise, ("OZON",)) == noise


def test_service_mode_cannot_run_on_holdout(tmp_path):
    script = Path(__file__).resolve().parents[1] / "checks/evaluate_extraction.py"
    result = subprocess.run(
        [sys.executable, str(script), "--service-literals", "--stage", "holdout"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2 and "только для native development" in result.stderr
