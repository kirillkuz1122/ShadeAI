"""QA TASK-18: выбор известных имён сервисов только из исходного текста."""

import hashlib
import re
from copy import deepcopy

SERVICE_PATTERN = re.compile(r"(?<!\w)(?:Ozon|Wildberries|Яндекс Go)(?!\w)", re.IGNORECASE)
MAX_SERVICES = 8


def literal_service_sha256():
    return hashlib.sha256(
        f"{SERVICE_PATTERN.pattern}:{MAX_SERVICES}:ignorecase".encode()
    ).hexdigest()


def literal_services(title: str, text: str) -> tuple[str, ...] | None:
    matches = {}
    for source in (title, text):
        for match in SERVICE_PATTERN.finditer(source):
            matches[match[0]] = None
            if len(matches) > MAX_SERVICES:
                return None
    return tuple(matches)


def restrict_service_schema(schema: dict, candidates: tuple[str, ...]) -> dict:
    narrowed = deepcopy(schema)
    if "$defs" in narrowed:
        event = narrowed["$defs"]["EventGenerationDraft"]
    elif narrowed["properties"]["category"].get("const") == "noise":
        return narrowed
    else:
        event = narrowed
    event["properties"]["service"] = {"enum": [None, *candidates]}
    return narrowed
