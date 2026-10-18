from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.analytics.engine import Gap, Observation, analyze, cluster


def history(days=28, timezone="Asia/Yekaterinburg", *, irregular=False, weekends=False):
    zone = ZoneInfo(timezone)
    start = datetime(2026, 10, 15, tzinfo=zone)
    rows = [Observation(start, "on", "ha_snapshot")]
    for index in range(days):
        day = start + timedelta(days=index)
        weekend = weekends and day.weekday() >= 5
        leave = day + timedelta(hours=11 if weekend else 8)
        arrive = day + timedelta(hours=22 if weekend else 18)
        if irregular:
            leave = day + timedelta(hours=5, minutes=(index * 137) % 600)
            arrive = day + timedelta(hours=16, minutes=(index * 173) % 420)
        for stamp, state in ((leave, "off"), (arrive, "on")):
            rows.append(Observation(stamp, state, "ha_state_changed", stamp))
    return start, rows, start + timedelta(days=days)


def run(rows, now, gaps=(), checkpoint=None, timezone="Asia/Yekaterinburg"):
    return analyze(rows, list(gaps), checkpoint or now, now=now, timezone=timezone)


def test_regular_history_separates_weekdays_weekends_and_reports_evidence():
    _, rows, now = history(weekends=True)
    result = run(rows, now)
    assert result["status"] == "ready" and len(result["profiles"]) == 4
    profiles = {(p["day_group"], p["kind"]): p for p in result["profiles"]}
    assert profiles["weekdays", "departure_home"]["center_minute"] == 8 * 60
    assert profiles["weekends", "departure_home"]["center_minute"] == 11 * 60
    assert profiles["weekdays", "arrival_home"]["center_minute"] == 18 * 60
    assert profiles["weekends", "arrival_home"]["center_minute"] == 22 * 60
    assert result["diagnostics"]["eligible_days"] == 28
    assert profiles["weekdays", "arrival_home"]["confidence"] == 1
    assert profiles["weekends", "arrival_home"]["confidence"] == 0.8
    assert all(p["support_days"] == p["eligible_days"] for p in profiles.values())


def test_irregular_history_has_no_confident_profile():
    _, rows, now = history(irregular=True)
    result = run(rows, now)
    assert result["status"] == "no_pattern" and not result["profiles"]


@pytest.mark.parametrize("days", [1, 3, 6])
def test_insufficient_calendar_span_never_makes_profile(days):
    _, rows, now = history(days)
    assert run(rows, now)["status"] == "insufficient_data"
    assert not run(rows, now)["profiles"]


def test_one_week_can_be_a_provisional_pattern_but_not_high_confidence():
    _, rows, now = history(7)
    result = run(rows, now)
    assert result["status"] == "ready"
    assert len(result["profiles"]) == 2
    assert all(p["confidence"] == 0.5 for p in result["profiles"])


def test_snapshots_are_not_transitions_even_if_they_jump_between_states():
    start, _, now = history()
    rows = [
        Observation(start + timedelta(days=i, hours=12), "on" if i % 2 else "off", "ha_snapshot")
        for i in range(28)
    ]
    result = run(rows, now)
    assert not result["profiles"]
    assert result["diagnostics"]["excluded_days"]["snapshot"] > 0


def test_gaps_remove_whole_days_and_do_not_restore_missing_arrivals():
    start, rows, now = history()
    gaps = [Gap(start + timedelta(days=3), start + timedelta(days=16))]
    result = run(rows, now, gaps)
    assert result["status"] == "insufficient_coverage" and not result["profiles"]
    assert result["diagnostics"]["excluded_days"]["gap"] == 13
    result = run(rows, now, [Gap(start, None)])
    assert not result["profiles"] and result["diagnostics"]["eligible_days"] == 0


def test_unknown_state_and_bad_clocks_exclude_days_not_invent_events():
    start, rows, now = history()
    unknown = start + timedelta(days=4, hours=9)
    bad = start + timedelta(days=6, hours=10)
    rows += [
        Observation(unknown, "unavailable", "ha_state_changed", unknown),
        Observation(bad, "on", "ha_state_changed", bad + timedelta(hours=1)),
    ]
    result = run(rows, now)
    assert result["diagnostics"]["excluded_days"]["unknown"] >= 1
    assert result["diagnostics"]["excluded_days"]["clock"] >= 1
    assert all(p["confidence"] < 1 for p in result["profiles"])


def test_duplicate_unchanged_state_does_not_increase_daily_support():
    _, rows, now = history()
    original = run(rows, now)
    duplicate = run([item for row in rows for item in [row, row]], now)
    assert duplicate["profiles"] == original["profiles"]


def test_no_transitions_and_current_partial_day_do_not_form_habits():
    start, _, now = history()
    assert run([Observation(start, "on", "ha_snapshot")], now)["status"] == "no_pattern"
    rows = [Observation(now, "on", "ha_snapshot")]
    for index in range(100):
        stamp = now + timedelta(seconds=index + 1)
        rows.append(Observation(stamp, "on" if index % 2 else "off", "ha_state_changed", stamp))
    assert not run(rows, now + timedelta(hours=1))["profiles"]


def test_circular_window_handles_midnight_and_a_sparse_outlier():
    stamp = datetime(2026, 10, 1, tzinfo=UTC)
    samples = [(1435 if i % 2 else 5, stamp + timedelta(days=i)) for i in range(10)]
    result = cluster(samples, 10, 1)
    assert result["wraps_midnight"] and result["support_days"] == 10
    assert result["center_minute"] in (0, 5, 1435)
    values = [(480, stamp + timedelta(days=i)) for i in range(5)] + [(530, stamp)]
    result = cluster(values, 6, 1)
    assert result["center_minute"] == 480 and result["support_days"] == 5


def test_dst_uses_full_local_days_and_wall_clock_time():
    _, rows, now = history(timezone="America/New_York")
    result = run(rows, now, timezone="America/New_York")
    assert result["diagnostics"]["eligible_days"] == 28
    assert all(p["center_minute"] in (480, 1080) for p in result["profiles"])


def test_history_limit_and_stale_checkpoint_are_conservative():
    start, rows, now = history()
    assert run(rows * 200, now)["status"] == "too_many_observations"
    result = run(rows, now, checkpoint=start + timedelta(days=3))
    assert not result["profiles"]
    assert result["diagnostics"]["eligible_days"] == 3


def test_excessive_flapping_and_future_checkpoint_are_not_trusted():
    start, rows, now = history()
    for index in range(12):
        stamp = start + timedelta(days=4, hours=9, minutes=index * 5)
        rows.append(Observation(stamp, "on" if index % 2 else "off", "ha_state_changed", stamp))
    result = run(rows, now)
    assert result["diagnostics"]["excluded_days"]["unstable"] == 1
    assert run(rows, now, checkpoint=now + timedelta(hours=1))["status"] == "invalid_checkpoint"
    assert run(rows, now, [Gap(start, None)] * 1001)["status"] == "too_many_gaps"
