"""Предварительная проверка разметки TASK-18 без импорта приложения/модели."""

import hashlib
import json
import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from checks.extraction_metrics import CATEGORIES, normalized

REGISTRY = Path(__file__).with_name("development-inputs.json")
MAX_BYTES = 1_048_576


class DatasetError(ValueError):
    pass


def input_signature(case):
    values = [" ".join(case[key].casefold().split()) for key in ("title", "text")]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DatasetError("Повторное имя поля JSON")
        result[key] = value
    return result


def require(condition, field):
    if not condition:
        raise DatasetError("Некорректная разметка: " + field)


def timestamp(value):
    require(
        isinstance(value, str)
        and bool(
            re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?"
                r"(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)",
                value,
            )
        ),
        "timestamp",
    )
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_dataset(path, stage="development"):
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        require(len(raw) <= MAX_BYTES, "размер набора")
        data = json.loads(raw, object_pairs_hook=unique_object)
        require(isinstance(data, dict), "корень")
        require(
            set(data) == {"version", "purpose", "timestamp", "timezone", "cases"}, "поля набора"
        )
        require(type(data["version"]) is int and data["version"] > 0, "version")
        require(isinstance(data["purpose"], str) and 0 < len(data["purpose"]) <= 1000, "purpose")
        require(isinstance(data["timezone"], str), "timezone")
        ZoneInfo(data["timezone"])
        require(
            timestamp(data["timestamp"]) <= datetime.now(UTC) + timedelta(minutes=5), "timestamp"
        )
        cases = data["cases"]
        require(isinstance(cases, list) and 1 <= len(cases) <= 500, "cases")
        ids, signatures = set(), set()
        for index, case in enumerate(cases):
            field = f"cases[{index}]"
            require(isinstance(case, dict), field)
            require(set(case) == {"id", "app_name", "title", "text", "expected"}, field)
            require(
                isinstance(case["id"], str) and bool(re.fullmatch(r"[\w-]{1,64}", case["id"])),
                field + ".id",
            )
            require(case["id"] not in ids, field + ".id duplicate")
            ids.add(case["id"])
            require(
                isinstance(case["app_name"], str)
                and len(case["app_name"]) <= 255
                and bool(
                    re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z0-9_]+)+", case["app_name"])
                ),
                field + ".app_name",
            )
            for key, limit in (("title", 512), ("text", 8192)):
                require(isinstance(case[key], str) and len(case[key]) <= limit, field + "." + key)
            signature = input_signature(case)
            require(signature not in signatures, field + ".duplicate_input")
            signatures.add(signature)
            expected = case["expected"]
            require(
                isinstance(expected, dict)
                and {"category", "priority", "time"}
                <= set(expected)
                <= {"category", "priority", "time", "subject", "location", "service"},
                field + ".expected",
            )
            require(expected["category"] in CATEGORIES, field + ".category")
            require(expected["priority"] in ("low", "default", "high"), field + ".priority")
            if expected["category"] == "reminder":
                require("subject" in expected, field + ".subject")
            for key, limit in (("subject", 160), ("location", 200), ("service", 80)):
                if key not in expected:
                    continue
                values = expected[key]
                require(isinstance(values, list) and 1 <= len(values) <= 20, field + "." + key)
                require(
                    all(
                        v is None
                        or isinstance(v, str)
                        and 0 < len(v) <= limit
                        and bool(normalized(v))
                        and any(normalized(v) in normalized(case[k]) for k in ("title", "text"))
                        for v in values
                    ),
                    field + "." + key,
                )
            time = expected["time"]
            require(
                isinstance(time, dict) and set(time) == {"resolution", "at", "date"},
                field + ".time",
            )
            resolution = time["resolution"]
            require(
                resolution in ("absent", "exact", "date_only", "unresolved"), field + ".resolution"
            )
            if resolution == "exact":
                require(
                    time["date"] is None
                    and isinstance(time["at"], str)
                    and time["at"].endswith("Z"),
                    field + ".time",
                )
                timestamp(time["at"])
            elif resolution == "date_only":
                require(
                    time["at"] is None
                    and isinstance(time["date"], str)
                    and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", time["date"])),
                    field + ".time",
                )
                date.fromisoformat(time["date"])
            else:
                require(time["at"] is None and time["date"] is None, field + ".time")
            if expected["category"] == "noise":
                require(
                    expected["priority"] == "low"
                    and resolution == "absent"
                    and all(expected.get(k) == [None] for k in ("subject", "location", "service")),
                    field + ".noise",
                )
        registry = json.loads(REGISTRY.read_text(), object_pairs_hook=unique_object)
        require(
            isinstance(registry, dict)
            and type(registry.get("version")) is int
            and registry["version"] == 1,
            "реестр dev",
        )
        hashes = registry.get("signatures")
        require(
            isinstance(hashes, list)
            and 1 <= len(hashes) <= 2000
            and all(isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) for v in hashes),
            "реестр dev",
        )
        known = set(hashes)
        require(len(known) == len(hashes), "дубли реестра dev")
        overlap = len(signatures & known)
        require(stage in {"development", "holdout"}, "stage")
        if stage == "holdout":
            require(not overlap, "holdout содержит известные development-примеры")
        return data, dict(
            dataset_sha256=hashlib.sha256(raw).hexdigest(),
            cases=len(cases),
            categories=dict(Counter(c["expected"]["category"] for c in cases)),
            known_development_overlap=overlap,
            stage=stage,
            independence="not established; no known overlap is necessary, not sufficient",
        )
    except DatasetError:
        raise
    except (OSError, ValueError, TypeError, KeyError, RecursionError, ZoneInfoNotFoundError):
        raise DatasetError("Невозможно проверить набор/реестр; содержимое не выводится") from None
