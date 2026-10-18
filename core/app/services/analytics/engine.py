"""Описательные временные профили присутствия; никаких команд или зависимостей LLM."""

import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from statistics import median
from zoneinfo import ZoneInfo

MAX_OBSERVATIONS = 10_000
RADIUS = 45


@dataclass(frozen=True)
class Observation:
    observed_at: datetime
    state: str | None
    source: str
    ha_timestamp: datetime | None = None


@dataclass(frozen=True)
class Gap:
    started_at: datetime
    ended_at: datetime | None


def distance(left: int, right: int) -> int:
    value = abs(left - right) % 1440
    return min(value, 1440 - value)


def hhmm(minute: int) -> str:
    minute %= 1440
    return f"{minute // 60:02d}:{minute % 60:02d}"


def cluster(samples, eligible_days: int, coverage: float):
    minimum = math.ceil(eligible_days * 0.8)
    if len(samples) < minimum:
        return None
    minutes = sorted(item[0] for item in samples)
    doubled = minutes + [value + 1440 for value in minutes]
    candidates = set(minutes)
    for index in range(len(minutes)):
        end = index
        while end + 1 < index + len(minutes) and doubled[end + 1] - doubled[index] <= 90:
            end += 1
        candidates.add(round((doubled[index] + doubled[end]) / 2) % 1440)
    best = None
    for center in sorted(candidates):
        matched = [item for item in samples if distance(item[0], center) <= RADIUS]
        if len(matched) < minimum:
            continue
        spread = median(distance(item[0], center) for item in matched)
        if spread > 15:
            continue
        # Эвристический score регулярности, не вероятность и не статистическая гарантия.
        score = len(matched) / eligible_days * min(eligible_days / 10, 1)
        score *= (1 - spread / RADIUS) * coverage
        candidate = (score, len(matched), -spread, -center)
        if best is None or candidate > best[0]:
            best = (candidate, center, spread, matched)
    if best is None:
        return None
    key, center, spread, matched = best
    return {
        "center_minute": center,
        "window_start": hhmm(center - RADIUS),
        "window_end": hhmm(center + RADIUS),
        "wraps_midnight": center - RADIUS < 0 or center + RADIUS >= 1440,
        "radius_minutes": RADIUS,
        "support_days": len(matched),
        "eligible_days": eligible_days,
        "dispersion_minutes": spread,
        "confidence": round(key[0], 4),
        "last_seen": max(item[1] for item in matched)
        .astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
    }


def analyze(
    observations: list[Observation],
    gaps: list[Gap],
    checkpoint: datetime | None,
    *,
    now: datetime,
    timezone: str,
) -> dict:
    zone = ZoneInfo(timezone)
    today = now.astimezone(zone).date()
    window_start = today - timedelta(days=30)
    result = {
        "version": 1,
        "status": "insufficient_data",
        "timezone": timezone,
        "window_start": window_start.isoformat(),
        "window_end": today.isoformat(),
        "profiles": [],
        "diagnostics": {"observations": len(observations)},
    }
    if len(gaps) > 1000:
        result["status"] = "too_many_gaps"
        return result
    if len(observations) > MAX_OBSERVATIONS:
        result["status"] = "too_many_observations"
        return result
    observations = sorted(
        (item for item in observations if item.observed_at <= now),
        key=lambda item: item.observed_at,
    )
    if checkpoint is not None and checkpoint > now + timedelta(seconds=120):
        result["status"] = "invalid_checkpoint"
        return result
    if not observations or checkpoint is None:
        return result
    times = [item.observed_at for item in observations]
    first_day = max(window_start, observations[0].observed_at.astimezone(zone).date())
    total_days = max(0, (today - first_day).days)
    bad_clock_days: set[date] = set()
    previous_ha = None
    for item in observations:
        if item.source != "ha_state_changed":
            previous_ha = None
            continue
        stamp = item.ha_timestamp
        observed_day = item.observed_at.astimezone(zone).date()
        if (
            stamp is None
            or abs((stamp - item.observed_at).total_seconds()) > 120
            or stamp.astimezone(zone).date() != observed_day
            or (previous_ha is not None and stamp < previous_ha)
        ):
            bad_clock_days.add(observed_day)
            if stamp is not None:
                bad_clock_days.add(stamp.astimezone(zone).date())
        if stamp is not None:
            previous_ha = stamp
    groups = {"weekdays": [], "weekends": []}
    samples = {(group, kind): [] for group in groups for kind in ("arrival_home", "departure_home")}
    excluded = {"coverage": 0, "gap": 0, "clock": 0, "unknown": 0, "snapshot": 0, "unstable": 0}
    for number in range(total_days):
        day = first_day + timedelta(days=number)
        start = datetime.combine(day, time.min, zone).astimezone(UTC)
        end = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC)
        begin, finish = bisect_left(times, start), bisect_left(times, end)
        previous = (
            observations[begin - 1].state
            if begin and observations[begin - 1].source in {"ha_snapshot", "ha_state_changed"}
            else None
        )
        rows = observations[begin:finish]
        if rows and rows[0].observed_at == start and rows[0].source == "ha_snapshot":
            previous = rows[0].state
        if checkpoint < end or previous not in {"on", "off"}:
            excluded["coverage"] += 1
            continue
        if any(
            gap.started_at < end and (gap.ended_at is None or gap.ended_at > start) for gap in gaps
        ):
            excluded["gap"] += 1
            continue
        if day in bad_clock_days:
            excluded["clock"] += 1
            continue
        transitions = []
        reason = None
        for item in rows:
            if item.state not in {"on", "off"} or item.source not in {
                "ha_snapshot",
                "ha_state_changed",
            }:
                reason = "unknown"
                break
            if item.source == "ha_snapshot":
                if item.state != previous:
                    reason = "snapshot"
                    break
            elif item.state != previous:
                stamp = item.ha_timestamp
                if stamp is None:
                    reason = "clock"
                    break
                local = stamp.astimezone(zone)
                transitions.append(
                    (
                        "arrival_home" if item.state == "on" else "departure_home",
                        local.hour * 60 + local.minute,
                        stamp,
                    )
                )
            previous = item.state
        if reason:
            excluded[reason] += 1
            continue
        if len(transitions) > 8 or any(
            (later[2] - earlier[2]).total_seconds() < 60
            for earlier, later in zip(transitions, transitions[1:], strict=False)
        ):
            excluded["unstable"] += 1
            continue
        group = "weekdays" if day.weekday() < 5 else "weekends"
        groups[group].append(day)
        for kind in ("arrival_home", "departure_home"):
            values = [item for item in transitions if item[0] == kind]
            if values:
                selected = values[-1] if kind == "arrival_home" else values[0]
                samples[group, kind].append((selected[1], selected[2]))
    eligible = sum(len(days) for days in groups.values())
    coverage = eligible / total_days if total_days else 0
    result["diagnostics"].update(
        {
            "total_days": total_days,
            "eligible_days": eligible,
            "coverage": round(coverage, 4),
            "excluded_days": excluded,
            "group_days": {group: len(days) for group, days in groups.items()},
        }
    )
    if total_days < 7 or eligible < 5:
        return result
    if coverage < 0.7:
        result["status"] = "insufficient_coverage"
        return result
    for group, days in groups.items():
        if len(days) < (5 if group == "weekdays" else 4):
            continue
        for kind in ("arrival_home", "departure_home"):
            profile = cluster(samples[group, kind], len(days), coverage)
            if profile is not None:
                result["profiles"].append({"kind": kind, "day_group": group, **profile})
    result["status"] = "ready" if result["profiles"] else "no_pattern"
    return result
