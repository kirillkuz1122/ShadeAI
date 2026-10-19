import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import Settings, settings
from app.db import base
from app.db.models import (
    AnalyticsState,
    HabitProfile,
    SensorHistory,
    TelemetryCheckpoint,
    TelemetryGap,
)
from app.services.analytics.service import AnalyticsService
from app.services.telemetry.store import naive

ENTITY = "binary_sensor.synthetic_presence"
NOW = datetime(2026, 11, 12, 0, tzinfo=UTC)


def configure(client, monkeypatch):
    monkeypatch.setattr(settings, "ha_telemetry_entities", [ENTITY])
    monkeypatch.setattr(settings, "analytics_presence_entity", ENTITY)
    monkeypatch.setattr(settings, "analytics_timezone", "UTC")
    monkeypatch.setattr(clock, "utcnow", lambda: NOW)
    service = AnalyticsService()
    client.app.state.analytics = service
    return service


async def seed():
    start = NOW - timedelta(days=28)
    async with base.async_session() as session, session.begin():
        # Полностью синтетическая история заменяет стартовый gap изолированного стенда.
        await session.execute(delete(TelemetryGap))
        session.add(
            SensorHistory(
                entity_id=ENTITY,
                state="on",
                source="ha_snapshot",
                attributes_json="{}",
                observed_at=naive(start),
                ha_timestamp=None,
            )
        )
        for index in range(28):
            for hour, value in ((8, "off"), (18, "on")):
                stamp = start + timedelta(days=index, hours=hour)
                session.add(
                    SensorHistory(
                        entity_id=ENTITY,
                        state=value,
                        source="ha_state_changed",
                        attributes_json="{}",
                        observed_at=naive(stamp),
                        ha_timestamp=naive(stamp),
                    )
                )
        await session.merge(TelemetryCheckpoint(id=1, last_seen=naive(NOW)))


def test_default_is_disabled_and_api_is_protected(client, auth_headers):
    assert client.get("/api/v1/habits").status_code == 401
    response = client.get("/api/v1/habits", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["habits"] == [] and data["analytics"]["status"] == "disabled"
    assert data["analytics"]["action_authorized"] is False


def test_analysis_source_must_be_an_explicitly_selected_presence_sensor():
    for value in ["sensor.temperature", ENTITY]:
        with pytest.raises(ValueError):
            Settings(_env_file=None, analytics_presence_entity=value, ha_telemetry_entities=[])
    assert Settings(_env_file=None, analytics_presence_entity="").analytics_presence_entity is None
    assert (
        Settings(
            _env_file=None, analytics_presence_entity=ENTITY, ha_telemetry_entities=[ENTITY]
        ).analytics_presence_entity
        == ENTITY
    )
    with pytest.raises(ValueError):
        Settings(_env_file=None, analytics_timezone="invalid-timezone")


def test_profiles_persist_with_stable_ids_and_have_no_action(
    client, auth_headers, monkeypatch, ha_mock
):
    service = configure(client, monkeypatch)
    client.portal.call(seed)
    client.portal.call(service.recompute)
    data = client.get("/api/v1/habits", headers=auth_headers).json()
    ids = [row["id"] for row in data["habits"]]
    assert len(ids) == 4 and len(set(ids)) == 4, json.dumps(data["analytics"])
    assert data["analytics"]["status"] == "ready"
    assert data["analytics"]["stale"] is False
    assert data["analytics"]["diagnostics"]["eligible_days"] == 28
    assert data["analytics"]["score_kind"] == "heuristic_regularity_not_probability"
    assert all(row["pattern"]["trigger"] == ENTITY for row in data["habits"])
    assert all(
        "action" not in row["pattern"] and "target" not in row["pattern"] for row in data["habits"]
    )
    assert not any("/services/" in request.url.path for request in ha_mock.requests)
    restarted = AnalyticsService()
    client.app.state.analytics = restarted
    old = client.get("/api/v1/habits", headers=auth_headers).json()
    assert [row["id"] for row in old["habits"]] == ids and old["analytics"]["stale"]
    client.portal.call(restarted.recompute)
    assert [
        row["id"] for row in client.get("/api/v1/habits", headers=auth_headers).json()["habits"]
    ] == ids


def test_changed_config_hides_old_profile_before_recompute(client, auth_headers, monkeypatch):
    service = configure(client, monkeypatch)
    client.portal.call(seed)
    client.portal.call(service.recompute)
    monkeypatch.setattr(settings, "analytics_timezone", "Asia/Yekaterinburg")
    changed = AnalyticsService()
    client.app.state.analytics = changed
    data = client.get("/api/v1/habits", headers=auth_headers).json()
    assert data["habits"] == [] and data["analytics"]["stale"]
    assert data["analytics"]["computed_at"] is None


def test_failed_atomic_snapshot_keeps_previous_profiles(client, auth_headers, monkeypatch):
    service = configure(client, monkeypatch)
    client.portal.call(seed)
    client.portal.call(service.recompute)
    before = client.get("/api/v1/habits", headers=auth_headers).json()["habits"]
    original = AsyncSession.merge

    async def fail(session, instance, **kwargs):
        if isinstance(instance, AnalyticsState):
            raise SQLAlchemyError("private-synthetic-db-error")
        return await original(session, instance, **kwargs)

    monkeypatch.setattr(AsyncSession, "merge", fail)
    with pytest.raises(SQLAlchemyError):
        client.portal.call(service.recompute)
    data = client.get("/api/v1/habits", headers=auth_headers).json()
    assert data["habits"] == before and data["analytics"]["stale"]
    assert "private-synthetic" not in json.dumps(data)


def test_disabled_start_clears_profiles_and_periodic_stop_is_safe(client, monkeypatch):
    service = configure(client, monkeypatch)
    client.portal.call(seed)
    client.portal.call(service.recompute)
    monkeypatch.setattr(settings, "analytics_presence_entity", None)
    disabled = AnalyticsService()
    client.portal.call(disabled.start)

    async def verify_empty():
        async with base.async_session() as session:
            assert list((await session.scalars(select(HabitProfile))).all()) == []
            assert await session.get(AnalyticsState, 1) is None
        await disabled.stop()
        await disabled.stop()

    client.portal.call(verify_empty)


def test_periodic_error_is_safe_and_stop_cancels_task(client, monkeypatch):
    service = configure(client, monkeypatch)
    ready = asyncio.Event()

    async def broken():
        ready.set()
        raise RuntimeError("private-internal-error")

    monkeypatch.setattr(service, "recompute", broken)

    async def scenario():
        await service.start()
        await asyncio.wait_for(ready.wait(), 2)
        assert service.status == "ANALYTICS_ERROR"
        await service.stop()
        await service.stop()
        assert service.task is None

    client.portal.call(scenario)


def test_cpu_analysis_is_off_loop_and_old_snapshot_is_marked_stale(
    client, auth_headers, monkeypatch
):
    import threading

    from app.services.analytics import service as module

    service = configure(client, monkeypatch)
    client.portal.call(seed)
    threads = []
    original = module.analyze

    def measured(*args, **kwargs):
        threads.append(threading.get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "analyze", measured)
    loop_thread = client.portal.call(threading.get_ident)
    client.portal.call(service.recompute)
    assert threads and all(value != loop_thread for value in threads)
    monkeypatch.setattr(clock, "utcnow", lambda: NOW + timedelta(seconds=service.interval * 3))
    data = client.get("/api/v1/habits", headers=auth_headers).json()
    assert data["habits"] and data["analytics"]["stale"]


def test_invalid_snapshot_does_not_expose_raw_data(client, auth_headers, monkeypatch):
    service = configure(client, monkeypatch)
    client.portal.call(seed)
    client.portal.call(service.recompute)

    async def corrupt():
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            row = await session.get(AnalyticsState, 1)
            row.snapshot_json = "private-synthetic-invalid-json"

    client.portal.call(corrupt)
    data = client.get("/api/v1/habits", headers=auth_headers).json()
    assert data["habits"] == [] and data["analytics"]["status"] == "ANALYTICS_INVALID_SNAPSHOT"
    assert "private-synthetic" not in json.dumps(data)
