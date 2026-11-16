"""TASK-20: чувствительность профиля к длине синтетической истории, без БД/HA."""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.services.analytics.engine import Gap, Observation, analyze

TIMEZONE = "Asia/Yekaterinburg"
WINDOWS = (7, 10, 14, 21, 28, 30)
REFERENCE_THRESHOLD = 0.75
PROFILES = ("weekdays", "weekends")
CONDITIONS = ("regular", "jitter_15min", "weekly_gap")


def scenario(first_weekday: int, days: int, condition: str):
    zone = ZoneInfo(TIMEZONE)
    start = datetime(2026, 10, 5, tzinfo=zone) + timedelta(days=first_weekday)
    end = start + timedelta(days=days)
    rows = [Observation(start, "on", "ha_snapshot")]
    gaps = []
    for index in range(days):
        day = start + timedelta(days=index)
        if condition == "weekly_gap" and index % 7 == 3:
            gaps.append(Gap(day, day + timedelta(days=1)))
            continue
        if condition == "weekly_gap" and index % 7 == 4:
            rows.append(Observation(day, "on", "ha_snapshot"))
        jitter = (-15, 0, 15)[index % 3] if condition == "jitter_15min" else 0
        for hour, state in ((8, "off"), (18, "on")):
            at = day + timedelta(hours=hour, minutes=jitter)
            rows.append(Observation(at, state, "ha_state_changed", at))
    result = analyze(rows, gaps, end, now=end, timezone=TIMEZONE)
    return {
        "status": result["status"],
        "eligible_days": result["diagnostics"]["eligible_days"],
        "arrival_confidence": {
            p["day_group"]: p["confidence"]
            for p in result["profiles"]
            if p["kind"] == "arrival_home"
        },
    }


def survey():
    summary = {}
    for condition in CONDITIONS:
        simulations = {
            (start, days): scenario(start, days, condition)
            for start in range(7)
            for days in range(1, 31)
        }
        summary[condition] = {
            "first_threshold_calendar_days_by_start_weekday": {
                group: [
                    next(
                        (
                            days
                            for days in range(1, 31)
                            if simulations[start, days]["arrival_confidence"].get(group, 0)
                            >= REFERENCE_THRESHOLD
                        ),
                        None,
                    )
                    for start in range(7)
                ]
                for group in PROFILES
            },
            "windows": {
                str(days): {
                    "eligible_days_range": [
                        min(simulations[start, days]["eligible_days"] for start in range(7)),
                        max(simulations[start, days]["eligible_days"] for start in range(7)),
                    ],
                    "starts_with_profile": {
                        group: sum(
                            group in simulations[start, days]["arrival_confidence"]
                            for start in range(7)
                        )
                        for group in PROFILES
                    },
                    "starts_at_or_over_reference_threshold": {
                        group: sum(
                            simulations[start, days]["arrival_confidence"].get(group, 0)
                            >= REFERENCE_THRESHOLD
                            for start in range(7)
                        )
                        for group in PROFILES
                    },
                }
                for days in WINDOWS
            },
        }
    return {
        "task": "TASK-20",
        "synthetic": True,
        "real_history": False,
        "hardware_acceptance": False,
        "runner": "app.services.analytics.engine.analyze",
        "timezone": TIMEZONE,
        "calendar_start_weekdays": ["пн", "вт", "ср", "чт", "пт", "сб", "вс"],
        "reference_confidence_for_suggestions": REFERENCE_THRESHOLD,
        "reference_is_not_probability": True,
        "simulations": len(CONDITIONS) * 7 * 30,
        "results": summary,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.output.open("x") as stream:
        result = survey()
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                condition: result["results"][condition][
                    "first_threshold_calendar_days_by_start_weekday"
                ]
                for condition in CONDITIONS
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
