"""Кандидаты времени для dev-стенда TASK-18; не часть рабочего Core."""

import hashlib
import re
from copy import deepcopy

CLOCK = r"(?:[01]?\d|2[0-3]):[0-5]\d"
DAY = r"(?:послезавтра|завтра|сегодня|\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})"
EXPRESSION = re.compile(
    rf"(?<![\w:\d])(?:(?:{DAY}\s+)?(?:между\s+{CLOCK}\s+и\s+{CLOCK}"
    rf"|с\s+{CLOCK}\s+до\s+{CLOCK}|{CLOCK}\s*[–—-]\s*{CLOCK})"
    rf"|через\s+\d{{1,3}}\s+(?:минут(?:у|ы)?|час(?:а|ов)?|д(?:ень|ня|ней))"
    rf"|{DAY}(?:\s+в\s+{CLOCK})?(?:\s+(?:утром|днём|днем|вечером|ночью))?"
    rf"|в\s+{CLOCK}|{CLOCK}|скоро|вечером|утром|ночью)(?![\w:\d])",
    re.IGNORECASE,
)
MAX_CANDIDATES = 12


def literal_time_sha256():
    return hashlib.sha256(f"{EXPRESSION.pattern}:{MAX_CANDIDATES}".encode()).hexdigest()


def literal_times(title: str, text: str) -> tuple[str, ...] | None:
    values = {}
    for source in (title, text):
        for match in EXPRESSION.finditer(source):
            literal = match[0]
            # Слишком длинный/грязный кандидат не перекраиваем в другое время.
            if len(literal) > 128 or any(ord(char) < 32 for char in literal):
                return None
            values[literal] = None
            if len(values) > MAX_CANDIDATES:
                return None
    return tuple(values)


def restrict_time_schema(schema: dict, candidates: tuple[str, ...]) -> dict:
    narrowed = deepcopy(schema)
    if "$defs" in narrowed:
        event = narrowed["$defs"]["EventGenerationDraft"]
    elif narrowed["properties"]["category"].get("const") == "noise":
        return narrowed
    else:
        event = narrowed
    event["properties"]["time_expression"] = {"enum": [None, *candidates]}
    return narrowed
