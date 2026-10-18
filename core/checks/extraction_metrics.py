import math
from collections import Counter

CATEGORIES = ("delivery", "transport", "calendar", "reminder", "noise")


def normalized(value):
    return " ".join(value.casefold().split()) if isinstance(value, str) else value


def score(expected, actual):
    fields = {}
    fields["category"] = actual is not None and actual["category"] == expected["category"]
    fields["priority"] = actual is not None and actual["priority"] == expected["priority"]
    for field in ("subject", "location", "service"):
        if field in expected:
            fields[field] = actual is not None and normalized(actual["entities"][field]) in [
                normalized(value) for value in expected[field]
            ]
    for field in ("resolution", "at", "date"):
        fields["time." + field] = (
            actual is not None and actual["time"][field] == expected["time"][field]
        )
    return fields


def wilson(correct, total):
    if not total:
        return None
    z = 1.959963984540054
    rate = correct / total
    center = rate + z * z / (2 * total)
    radius = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total))
    denominator = 1 + z * z / total
    return [round((center - radius) / denominator, 4), round((center + radius) / denominator, 4)]


def summarize(rows):
    total = len(rows)
    per_class = {}
    for category in CATEGORIES:
        tp = sum(
            row["expected_category"] == category and row["predicted_category"] == category
            for row in rows
        )
        fp = sum(
            row["expected_category"] != category and row["predicted_category"] == category
            for row in rows
        )
        fn = sum(
            row["expected_category"] == category and row["predicted_category"] != category
            for row in rows
        )
        precision = tp / (tp + fp) if tp + fp else 0
        recall = tp / (tp + fn) if tp + fn else 0
        per_class[category] = {
            "support": tp + fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(2 * precision * recall / (precision + recall), 4)
            if precision + recall
            else 0,
        }
    field_totals, field_correct = Counter(), Counter()
    for row in rows:
        for field, correct in row["fields"].items():
            field_totals[field] += 1
            field_correct[field] += int(correct)
    latency = sorted(row["elapsed_ms"] for row in rows)
    courier_reminder = [row for row in rows if row["expected_category"] in {"delivery", "reminder"}]
    correct = sum(row["exact_match"] for row in courier_reminder)
    return {
        "total": total,
        "valid": sum(row["result"] is not None for row in rows),
        "classification_correct": sum(row["fields"]["category"] for row in rows),
        "classification_accuracy": round(sum(row["fields"]["category"] for row in rows) / total, 4)
        if total
        else 0,
        "macro_f1": round(sum(value["f1"] for value in per_class.values()) / len(CATEGORIES), 4),
        "per_class": per_class,
        "fields": {
            field: {
                "correct": field_correct[field],
                "total": count,
                "accuracy": round(field_correct[field] / count, 4),
            }
            for field, count in field_totals.items()
        },
        "exact_match": sum(row["exact_match"] for row in rows),
        "courier_reminder": {
            "correct": correct,
            "total": len(courier_reminder),
            "accuracy": round(correct / len(courier_reminder), 4) if courier_reminder else 0,
            "wilson_95": wilson(correct, len(courier_reminder)),
            "inference": (
                "reference-only; synthetic nonrandom cases do not establish population accuracy"
            ),
            "sample_target_90_percent": bool(courier_reminder)
            and correct / len(courier_reminder) >= 0.9,
        },
        "processor_ms": {
            "p50": latency[math.ceil(total * 0.5) - 1] if total else None,
            "p95": latency[math.ceil(total * 0.95) - 1] if total else None,
            "max": max(latency) if latency else None,
            "sample_target_4_seconds": bool(total) and max(latency) <= 4000,
        },
    }
