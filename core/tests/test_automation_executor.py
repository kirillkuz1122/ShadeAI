import asyncio
import json
from datetime import UTC, datetime, timedelta
from functools import partial

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from app.core import clock
from app.core.config import Settings, settings
from app.db import base
from app.db.models import AutomationRun, EventLog, SensorHistory, TelemetryCheckpoint, TelemetryGap
from app.services.automation.executor import AutomationExecutor, in_window
from app.services.suggestions.service import SuggestionError, SuggestionService
from app.services.telemetry.store import naive
from tests.test_analytics_service import ENTITY, configure, seed
from tests.test_suggestions import decide

HOME = "binary_sensor.synthetic_whole_home"
NOW = datetime(2026, 11, 12, 18, tzinfo=UTC)
LIGHT = "light.test"


def setup(client, headers, monkeypatch, kind="arrival_home"):
    client.portal.call(client.app.state.telemetry.stop)
    analytics = configure(client, monkeypatch)
    monkeypatch.setattr(
        clock, "utcnow", lambda: NOW if kind == "arrival_home" else NOW.replace(hour=8)
    )
    monkeypatch.setattr(settings, "ha_telemetry_entities", [ENTITY, HOME])
    monkeypatch.setattr(settings, "automation_allowed_lights", [LIGHT])
    monkeypatch.setattr(settings, "automation_execution_enabled", True)
    monkeypatch.setattr(settings, "automation_home_presence_entity", HOME)
    client.portal.call(seed)
    client.portal.call(analytics.recompute)
    suggestions = SuggestionService(analytics, client.app.state.telemetry)
    client.app.state.suggestions = suggestions
    client.portal.call(suggestions.refresh)
    rules = client.get("/api/v1/automations", headers=headers).json()["automations"]
    rule = next(
        row
        for row in rules
        if row["trigger"]["kind"] == kind and row["trigger"]["day_group"] == "weekdays"
    )
    executor = AutomationExecutor(
        suggestions, client.app.state.telemetry, client.app.state.ha_client
    )
    client.app.state.automation_executor = executor
    response = decide(client, headers, rule, target=LIGHT)
    assert response.status_code == 200
    client.app.state.telemetry.status = "connected"
    client.portal.call(partial(observe, clock.utcnow(), kind))
    return executor, response.json()


async def observe(
    now, kind="arrival_home", *, home_state=None, source="ha_state_changed", gap=False, age=0
):
    to_state = "on" if kind == "arrival_home" else "off"
    from_state = "off" if to_state == "on" else "on"
    async with base.async_session() as session, session.begin():
        for entity in (ENTITY, HOME):
            for before in (True, False):
                at = naive(now - timedelta(seconds=age + (60 if before else 0)))
                session.add(
                    SensorHistory(
                        entity_id=entity,
                        state=from_state
                        if before
                        else home_state
                        if entity == HOME and home_state
                        else to_state,
                        source="ha_snapshot" if before else source,
                        attributes_json="{}",
                        observed_at=at,
                        ha_timestamp=at,
                    )
                )
        await session.merge(TelemetryCheckpoint(id=1, last_seen=naive(now)))
        if gap:
            session.add(
                TelemetryGap(started_at=naive(now - timedelta(seconds=10)), reason="synthetic")
            )


def advance(monkeypatch, seconds=31):
    stamp = clock.utcnow() + timedelta(seconds=seconds)
    monkeypatch.setattr(clock, "utcnow", lambda: stamp)


def runs(client, headers):
    response = client.get("/api/v1/automations/runs", headers=headers)
    assert response.status_code == 200
    return response.json()["runs"]


def sent(mock):
    return [r for r in mock.requests if r.method == "POST" and "/services/" in r.url.path]


def test_default_disabled_and_protected(client, auth_headers, ha_mock):
    assert client.get("/api/v1/automations/runs").status_code == 401
    assert client.post("/api/v1/automations/runs/1/cancel").status_code == 401
    assert runs(client, auth_headers) == []
    client.portal.call(client.app.state.automation_executor.tick)
    assert not sent(ha_mock)
    assert client.post("/api/v1/automations/runs/1/cancel", headers=auth_headers).status_code == 404


@pytest.mark.parametrize(
    "kind,service", [("arrival_home", "turn_on"), ("departure_home", "turn_off")]
)
def test_two_sources_wait_then_audit_and_exactly_one_attempt(
    client, auth_headers, monkeypatch, ha_mock, kind, service
):
    executor, rule = setup(client, auth_headers, monkeypatch, kind)
    client.portal.call(executor.tick)
    first = runs(client, auth_headers)[0]
    assert first["state"] == "pending" and first["cancellable"] and not sent(ha_mock)
    client.portal.call(executor.tick)
    assert len(runs(client, auth_headers)) == 1
    advance(monkeypatch)
    client.portal.call(executor.tick)
    finished = runs(client, auth_headers)[0]
    assert finished["state"] == "succeeded" and finished["reason"] == "HA_ACCEPTED"
    assert finished["event_id"] is not None and not finished["cancellable"]
    assert len(sent(ha_mock)) == 1 and sent(ha_mock)[0].url.path.endswith(service)
    assert json.loads(sent(ha_mock)[0].content) == {"entity_id": LIGHT}
    client.portal.call(executor.tick)
    assert len(sent(ha_mock)) == 1
    assert (
        client.post(
            f"/api/v1/automations/runs/{first['id']}/cancel", headers=auth_headers
        ).status_code
        == 409
    )
    assert rule["execution_policy"]["home_presence_entity"] == HOME


def test_explicit_cancellation_is_sticky_and_rule_disable_cancels_pending(
    client, auth_headers, monkeypatch, ha_mock
):
    executor, rule = setup(client, auth_headers, monkeypatch)
    client.portal.call(executor.tick)
    identity = runs(client, auth_headers)[0]["id"]
    url = f"/api/v1/automations/runs/{identity}/cancel"
    assert client.post(url, headers=auth_headers).status_code == 200
    assert client.post(url, headers=auth_headers).status_code == 200
    advance(monkeypatch)
    client.portal.call(executor.tick)
    assert len(runs(client, auth_headers)) == 1 and not sent(ha_mock)
    assert runs(client, auth_headers)[0]["reason"] == "USER_CANCELLED"
    client.portal.call(partial(observe, clock.utcnow()))
    client.portal.call(executor.tick)
    assert runs(client, auth_headers)[0]["state"] == "pending"
    assert decide(client, auth_headers, rule, "disable").status_code == 200
    assert runs(client, auth_headers)[0]["reason"] == "RULE_DISABLED"
    advance(monkeypatch)
    client.portal.call(executor.tick)
    assert not sent(ha_mock)


@pytest.mark.parametrize(
    "defect",
    ["other_person", "snapshot", "gap", "old", "disconnected", "unknown", "clock", "unpaired"],
)
def test_unconfirmed_sources_never_schedule(client, auth_headers, monkeypatch, ha_mock, defect):
    kind = "departure_home" if defect == "other_person" else "arrival_home"
    executor, _ = setup(client, auth_headers, monkeypatch, kind)
    if defect in {"other_person", "snapshot", "gap", "old", "unknown"}:
        client.portal.call(
            partial(
                observe,
                clock.utcnow(),
                kind,
                home_state="on"
                if defect == "other_person"
                else "unknown"
                if defect == "unknown"
                else None,
                source="ha_snapshot" if defect == "snapshot" else "ha_state_changed",
                gap=defect == "gap",
                age=301 if defect == "old" else 0,
            )
        )
    elif defect == "disconnected":
        client.app.state.telemetry.status = "disconnected"
    else:

        async def corrupt():
            async with base.async_session() as session, session.begin():
                row = await session.scalar(
                    select(SensorHistory)
                    .where(SensorHistory.entity_id == HOME)
                    .order_by(SensorHistory.id.desc())
                    .limit(1)
                )
                if defect == "clock":
                    row.ha_timestamp = row.observed_at + timedelta(hours=1)
                else:
                    row.observed_at -= timedelta(seconds=91)

        client.portal.call(corrupt)
    client.portal.call(executor.tick)
    assert runs(client, auth_headers) == [] and not sent(ha_mock)


def test_source_change_during_cancel_window_cancels_without_command(
    client, auth_headers, monkeypatch, ha_mock
):
    executor, _ = setup(client, auth_headers, monkeypatch)
    client.portal.call(executor.tick)
    assert runs(client, auth_headers)[0]["state"] == "pending"
    advance(monkeypatch)
    client.portal.call(partial(observe, clock.utcnow(), "departure_home"))
    client.portal.call(executor.tick)
    assert runs(client, auth_headers)[0]["reason"] == "PRESENCE_UNCONFIRMED"
    assert not sent(ha_mock)


def test_new_execution_policy_invalidates_old_consent(client, auth_headers, monkeypatch, ha_mock):
    executor, rule = setup(client, auth_headers, monkeypatch)
    client.portal.call(executor.tick)
    monkeypatch.setattr(settings, "automation_cooldown_seconds", 3600)
    changed = SuggestionService(executor.suggestions.analytics, executor.telemetry)
    client.app.state.suggestions = changed
    executor.suggestions = changed
    client.portal.call(changed.refresh)
    advance(monkeypatch)
    client.portal.call(executor.tick)
    assert runs(client, auth_headers)[0]["reason"] == "APPROVAL_CHANGED" and not sent(ha_mock)
    row = client.get(f"/api/v1/automations/{rule['id']}", headers=auth_headers).json()
    assert row["status"] == "needs_review" and not row["approval_valid"]


def test_cooldown_is_persistent_across_new_transitions(client, auth_headers, monkeypatch, ha_mock):
    executor, _ = setup(client, auth_headers, monkeypatch)
    client.portal.call(executor.tick)
    advance(monkeypatch)
    client.portal.call(executor.tick)
    advance(monkeypatch, 10)
    client.portal.call(partial(observe, clock.utcnow()))
    client.portal.call(executor.tick)
    advance(monkeypatch)
    client.portal.call(executor.tick)
    assert runs(client, auth_headers)[0]["reason"] == "COOLDOWN"
    assert len(sent(ha_mock)) == 1


@pytest.mark.parametrize("phase", ["pending", "dispatching"])
def test_restart_never_replays_pending_or_unknown(
    client, auth_headers, monkeypatch, ha_mock, phase
):
    executor, _ = setup(client, auth_headers, monkeypatch)
    client.portal.call(executor.tick)

    async def mark():
        async with base.async_session() as session, session.begin():
            await session.execute(
                update(AutomationRun).values(
                    state=phase,
                    started_at=naive(clock.utcnow()) if phase == "dispatching" else None,
                )
            )

    client.portal.call(mark)
    recovered = AutomationExecutor(executor.suggestions, executor.telemetry, executor.client)
    recovered.enabled = False
    client.portal.call(recovered.start)
    recovered.enabled = True
    advance(monkeypatch)
    client.portal.call(recovered.tick)
    assert runs(client, auth_headers)[0]["state"] == (
        "cancelled" if phase == "pending" else "unknown"
    )
    assert not sent(ha_mock)


def test_ha_timeout_is_unknown_and_not_retried(client, auth_headers, monkeypatch, ha_mock):
    executor, _ = setup(client, auth_headers, monkeypatch)
    client.portal.call(executor.tick)
    advance(monkeypatch)
    ha_mock.error = httpx.ReadTimeout("synthetic")
    client.portal.call(executor.tick)
    assert runs(client, auth_headers)[0]["state"] == "unknown"
    assert runs(client, auth_headers)[0]["reason"] == "HA_UNCONFIRMED"
    client.portal.call(executor.tick)
    assert len(sent(ha_mock)) == 1


def test_no_command_when_audit_cannot_commit(client, auth_headers, monkeypatch, ha_mock):
    executor, _ = setup(client, auth_headers, monkeypatch)
    client.portal.call(executor.tick)
    advance(monkeypatch)
    from sqlalchemy.ext.asyncio import AsyncSession

    original = AsyncSession.commit

    async def fail_pending(self):
        if any(isinstance(row, EventLog) for row in self.new):
            raise SQLAlchemyError("synthetic-private-do-not-expose")
        return await original(self)

    monkeypatch.setattr(AsyncSession, "commit", fail_pending)
    client.portal.call(executor.tick)
    data = runs(client, auth_headers)
    assert data[0]["state"] == "failed" and data[0]["reason"] == "AUDIT_UNAVAILABLE"
    assert "synthetic-private" not in json.dumps(data) and not sent(ha_mock)


def test_two_ticks_cannot_dispatch_twice(client, auth_headers, monkeypatch, ha_mock):
    executor, _ = setup(client, auth_headers, monkeypatch)
    client.portal.call(executor.tick)
    advance(monkeypatch)

    async def concurrent():
        await asyncio.gather(executor.tick(), executor.tick())

    client.portal.call(concurrent)
    assert len(sent(ha_mock)) == 1


def test_config_requires_distinct_selected_sources_and_explicit_light(monkeypatch):
    kwargs = dict(
        automation_execution_enabled=True,
        automation_home_presence_entity=HOME,
        analytics_presence_entity=ENTITY,
        ha_telemetry_entities=[ENTITY, HOME],
        automation_allowed_lights=[LIGHT],
    )
    assert Settings(_env_file=None, **kwargs).automation_execution_enabled
    for change in (
        {"automation_home_presence_entity": ENTITY},
        {"automation_home_presence_entity": None},
        {"ha_telemetry_entities": [ENTITY]},
        {"automation_allowed_lights": []},
    ):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **(kwargs | change))


def test_window_day_group_timezone_and_midnight():
    condition = dict(
        timezone="Asia/Yekaterinburg",
        day_group="weekdays",
        window_start="23:45",
        window_end="00:15",
    )
    assert in_window(condition, datetime(2026, 11, 12, 19))
    assert not in_window(condition, datetime(2026, 11, 12, 20))
    assert not in_window(condition, datetime(2026, 11, 13, 19))


def test_slow_ha_releases_db_and_disable_cannot_recall_inflight(client, auth_headers, monkeypatch):
    executor, rule = setup(client, auth_headers, monkeypatch)
    client.portal.call(executor.tick)
    advance(monkeypatch)
    original = executor.client.call_service

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        async def slow(*args):
            started.set()
            await release.wait()
            return await original(*args)

        monkeypatch.setattr(executor.client, "call_service", slow)
        job = asyncio.create_task(executor.tick())
        await asyncio.wait_for(started.wait(), 2)
        # Другая пишущая транзакция проходит, пока HA ожидает: lock БД не удерживается.
        async with asyncio.timeout(2):
            await executor.suggestions.decide(rule["id"], "disable", 1, None)
            async with base.async_session() as session:
                row = await session.scalar(select(AutomationRun))
                assert row.state == "dispatching"
                with pytest.raises(SuggestionError) as caught:
                    await executor.cancel(row.id)
                assert caught.value.code == "AUTOMATION_RUN_ALREADY_DISPATCHED"
        release.set()
        await asyncio.wait_for(job, 2)

    client.portal.call(scenario)
    assert runs(client, auth_headers)[0]["state"] == "succeeded"


def test_failed_run_finalization_does_not_retry_network(client, auth_headers, monkeypatch, ha_mock):
    from sqlalchemy.ext.asyncio import AsyncSession

    executor, _ = setup(client, auth_headers, monkeypatch)
    client.portal.call(executor.tick)
    advance(monkeypatch)
    original = AsyncSession.execute

    async def fail_result(self, statement, *args, **kwargs):
        if getattr(statement, "is_update", False) and statement.table.name == "automation_runs":
            raise SQLAlchemyError("synthetic result commit failure")
        return await original(self, statement, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "execute", fail_result)
        with pytest.raises(SQLAlchemyError):
            client.portal.call(executor.tick)
    assert runs(client, auth_headers)[0]["state"] == "dispatching"
    client.portal.call(executor.tick)
    assert len(sent(ha_mock)) == 1


def test_clock_rollback_blocks_future_profile_consent(client, auth_headers, monkeypatch, ha_mock):
    executor, rule = setup(client, auth_headers, monkeypatch)
    earlier = clock.utcnow() - timedelta(minutes=1)
    monkeypatch.setattr(clock, "utcnow", lambda: earlier)
    data = client.get(f"/api/v1/automations/{rule['id']}", headers=auth_headers).json()
    assert not data["source_current"] and not data["approval_valid"] and not data["executable"]
    client.portal.call(executor.tick)
    assert not runs(client, auth_headers) and not sent(ha_mock)


def test_capacity_preserves_recent_dedupe_and_prunes_old_terminal_runs(
    client, auth_headers, monkeypatch, ha_mock
):
    from sqlalchemy import func, insert

    executor, rule = setup(client, auth_headers, monkeypatch)
    now = naive(clock.utcnow())

    async def populate():
        async with base.async_session() as session, session.begin():
            await session.execute(
                insert(AutomationRun),
                [
                    dict(
                        identity=f"synthetic-{i}",
                        rule_id=rule["id"],
                        approval_key="old",
                        primary_event_id=i,
                        home_event_id=i,
                        target_entity=LIGHT,
                        service="turn_on",
                        state="cancelled",
                        reason="USER_CANCELLED",
                        created_at=now,
                        due_at=now,
                        finished_at=now,
                    )
                    for i in range(1000)
                ],
            )

    client.portal.call(populate)
    client.portal.call(executor.tick)
    assert executor.capacity_full and not sent(ha_mock)

    async def age():
        async with base.async_session() as session, session.begin():
            await session.execute(update(AutomationRun).values(finished_at=now - timedelta(days=2)))

    client.portal.call(age)
    client.portal.call(executor.tick)
    assert not executor.capacity_full and runs(client, auth_headers)[0]["state"] == "pending"

    async def count():
        async with base.async_session() as session:
            return await session.scalar(select(func.count()).select_from(AutomationRun))

    assert client.portal.call(count) <= 1000


def test_enabled_execution_requires_matching_displayed_scope(
    client, auth_headers, monkeypatch, ha_mock
):
    _, rule = setup(client, auth_headers, monkeypatch)
    body = dict(decision="accept", version=rule["version"], target_entity=LIGHT)
    url = f"/api/v1/automations/{rule['id']}/decision"
    for scope in (None, "a" * 64):
        attempt = body if scope is None else body | {"approval_scope": scope}
        response = client.post(url, headers=auth_headers, json=attempt)
        assert (
            response.status_code == 409
            and response.json()["detail"]["code"] == "AUTOMATION_SCOPE_CHANGED"
        )
    assert (
        client.post(
            url, headers=auth_headers, json=body | {"approval_scope": rule["approval_scope"]}
        ).status_code
        == 200
    )
    assert not sent(ha_mock)
