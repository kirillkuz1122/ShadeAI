import asyncio
import json
from datetime import timedelta
from functools import partial

import pytest
from sqlalchemy import delete, event
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db import base
from app.db.models import (
    HabitProfile,
    NotificationRaw,
    SensorHistory,
    TelemetryCheckpoint,
    TelemetryGap,
)
from app.services.notification.extraction import (
    ExtractedEntities,
    ExtractedNotification,
    ExtractedTime,
)
from app.services.suggestions.service import SuggestionError, SuggestionService
from app.services.telemetry.store import naive
from tests.test_analytics_service import ENTITY, NOW, configure, seed

LIGHT = "light.synthetic_entry"


def setup(client, monkeypatch):
    client.portal.call(client.app.state.telemetry.stop)
    analytics = configure(client, monkeypatch)
    monkeypatch.setattr(settings, "automation_allowed_lights", [LIGHT])
    client.portal.call(seed)
    client.portal.call(analytics.recompute)
    service = SuggestionService(analytics, client.app.state.telemetry)
    client.app.state.suggestions = service
    client.portal.call(service.refresh)
    return service


def first(client, headers):
    return client.get("/api/v1/automations", headers=headers).json()["automations"][0]


def decide(client, headers, rule, decision="accept", version=None, target=LIGHT):
    body = {"decision": decision, "version": rule["version"] if version is None else version}
    if decision == "accept":
        body["target_entity"] = target
        if rule.get("approval_scope") is not None:
            body["approval_scope"] = rule["approval_scope"]
    return client.post(f"/api/v1/automations/{rule['id']}/decision", headers=headers, json=body)


def test_default_is_protected_empty_and_has_no_execution(client, auth_headers):
    assert client.get("/api/v1/automations").status_code == 401
    assert client.get("/api/v1/hints").status_code == 401
    data = client.get("/api/v1/automations", headers=auth_headers).json()
    assert data["automations"] == [] and data["allowed_targets"] == []
    assert data["executor_status"] == "disabled"
    hints = client.get("/api/v1/hints", headers=auth_headers).json()
    assert hints["hints"] == [] and hints["latest_id"] == 0
    assert len(hints["feed_id"]) == 36


def test_proposals_explain_source_and_only_explicit_target_can_be_accepted(
    client, auth_headers, monkeypatch, ha_mock
):
    service = setup(client, monkeypatch)
    data = client.get("/api/v1/automations?limit=2", headers=auth_headers).json()
    assert data["total"] == 4 and len(data["automations"]) == 2
    rule = first(client, auth_headers)
    assert rule["status"] == "pending" and not rule["enabled"]
    assert rule["confidence"] >= 0.75 and rule["evidence"]["support_days"] >= 4
    assert rule["source_current"] and rule["action"] is None
    assert decide(client, auth_headers, rule, target="light.not_allowed").status_code == 422
    assert first(client, auth_headers)["status"] == "pending"
    response = decide(client, auth_headers, rule)
    assert response.status_code == 200
    accepted = response.json()
    assert accepted["status"] == "accepted" and accepted["approval_valid"] and accepted["enabled"]
    assert not accepted["executable"] and accepted["action"]["entity_id"] == LIGHT
    assert accepted["action"]["params"] == {}
    assert accepted["action"]["service"] in {"turn_on", "turn_off"}
    assert not any("/services/" in request.url.path for request in ha_mock.requests)
    history = client.get(f"/api/v1/automations/{rule['id']}", headers=auth_headers).json()[
        "history"
    ]
    assert [row["decision"] for row in history] == ["accept", "suggested"]
    client.portal.call(service.refresh)
    assert first(client, auth_headers)["approval_valid"]


def test_rejection_and_disable_are_sticky_and_stale_accept_is_rejected(
    client, auth_headers, monkeypatch
):
    service = setup(client, monkeypatch)
    rule = first(client, auth_headers)
    rejected = decide(client, auth_headers, rule, "reject").json()
    for _ in range(2):
        client.portal.call(service.refresh)
    assert first(client, auth_headers)["status"] == "rejected"
    assert decide(client, auth_headers, rule).status_code == 409
    accepted = decide(client, auth_headers, rejected).json()
    assert accepted["approval_valid"]
    stopped = decide(client, auth_headers, accepted, "disable", version=1).json()
    assert stopped["status"] == "disabled" and not stopped["enabled"]
    client.portal.call(service.refresh)
    assert first(client, auth_headers)["status"] == "disabled"


def test_changed_source_and_revoked_policy_require_new_approval(client, auth_headers, monkeypatch):
    service = setup(client, monkeypatch)
    rule = first(client, auth_headers)
    accepted = decide(client, auth_headers, rule).json()

    async def change_profile():
        async with base.async_session() as session, session.begin():
            source = await session.get(HabitProfile, rule["source_habit_id"])
            data = json.loads(source.profile_json)
            data["window_start"], data["window_end"] = "10:00", "11:30"
            source.profile_json = json.dumps(data)

    client.portal.call(change_profile)
    client.portal.call(service.refresh)
    changed = first(client, auth_headers)
    assert changed["status"] == "needs_review" and not changed["approval_valid"]
    assert changed["version"] > accepted["version"]
    assert decide(client, auth_headers, accepted).status_code == 409
    assert decide(client, auth_headers, changed).status_code == 200
    service.allowed = ()
    client.portal.call(service.refresh)
    assert first(client, auth_headers)["status"] == "needs_review"
    service.allowed = (LIGHT,)
    client.portal.call(service.refresh)
    assert not first(client, auth_headers)["approval_valid"]


def test_concurrent_accepts_with_same_version_do_not_double_commit(
    client, auth_headers, monkeypatch
):
    setup(client, monkeypatch)
    rule = first(client, auth_headers)

    async def race():
        service = client.app.state.suggestions
        return await asyncio.gather(
            *[service.decide(rule["id"], "accept", rule["version"], LIGHT) for _ in range(2)],
            return_exceptions=True,
        )

    result = client.portal.call(race)
    errors = [item for item in result if isinstance(item, Exception)]
    assert len(errors) == 1 and isinstance(errors[0], SuggestionError)
    assert errors[0].code == "AUTOMATION_CHANGED" and errors[0].status == 409
    history = client.get(f"/api/v1/automations/{rule['id']}", headers=auth_headers).json()[
        "history"
    ]
    assert [item["decision"] for item in history].count("accept") == 1


def test_failed_decision_rolls_back_and_private_body_is_not_returned(
    client, auth_headers, monkeypatch
):
    setup(client, monkeypatch)
    rule = first(client, auth_headers)

    def fail(connection, cursor, statement, parameters, context, many):
        if statement.startswith("UPDATE automation_rules"):
            raise SQLAlchemyError("private-synthetic-write-error")

    event.listen(base.engine.sync_engine, "before_cursor_execute", fail)
    try:
        response = decide(client, auth_headers, rule)
        assert response.status_code == 503
        assert "private-synthetic" not in response.text
    finally:
        event.remove(base.engine.sync_engine, "before_cursor_execute", fail)
    current = first(client, auth_headers)
    assert current["status"] == "pending" and current["version"] == rule["version"]
    bad = client.post(
        f"/api/v1/automations/{rule['id']}/decision",
        headers=auth_headers,
        json={
            "decision": "accept",
            "version": True,
            "target_entity": "private-target",
            "params": {"secret": "private-text"},
        },
    )
    assert (
        bad.status_code == 422
        and "private-text" not in bad.text
        and "private-target" not in bad.text
    )
    huge = client.post(
        f"/api/v1/automations/{rule['id']}/decision", headers=auth_headers, content=b"x" * 65537
    )
    assert huge.status_code == 413


async def hint_context(*, snapshot=False, gap=False, invalid_llm=False):
    private = "private-synthetic-context-not-for-hint"
    result = ExtractedNotification(
        category="delivery",
        priority="default",
        intent="delivery_event",
        entities=ExtractedEntities(subject=private, location=None, service=None),
        time=ExtractedTime(source=None, timezone="UTC", at=None, date=None, resolution="absent"),
    )
    from uuid import uuid4

    from app.schemas import NotificationIn
    from app.services.notification.store import identity

    admitted = NotificationIn(
        app_name="ru.ozon.app.android",
        title="Контрольный контекст",
        text=private,
        timestamp=NOW.isoformat(),
        priority="default",
        event_id=uuid4(),
    )
    dedupe_key, payload_hash = identity(admitted)
    async with base.async_session() as session, session.begin():
        await session.execute(delete(TelemetryGap))
        for stamp, value, source in (
            (NOW - timedelta(minutes=2), "off", "ha_snapshot"),
            (NOW - timedelta(seconds=30), "on", "ha_snapshot" if snapshot else "ha_state_changed"),
        ):
            session.add(
                SensorHistory(
                    entity_id=ENTITY,
                    state=value,
                    source=source,
                    attributes_json="{}",
                    observed_at=naive(stamp),
                    ha_timestamp=naive(stamp),
                )
            )
        await session.merge(TelemetryCheckpoint(id=1, last_seen=naive(NOW)))
        if gap:
            session.add(
                TelemetryGap(started_at=naive(NOW - timedelta(minutes=1)), reason="synthetic")
            )
        session.add(
            NotificationRaw(
                app_name="ru.ozon.app.android",
                title="Контрольный контекст",
                text=private,
                timestamp=admitted.timestamp,
                dedupe_key=dedupe_key,
                payload_hash=payload_hash,
                priority="default",
                category="delivery",
                is_processed=1,
                processing_status="processed",
                extracted_data_json="{}" if invalid_llm else result.model_dump_json(),
                created_at=naive(NOW),
            )
        )


def test_arrival_hint_uses_only_valid_context_and_is_idempotent_per_client(
    client, auth_headers, monkeypatch
):
    service = setup(client, monkeypatch)
    client.app.state.telemetry.status = "connected"
    client.portal.call(hint_context)
    client.portal.call(service.refresh)
    client.portal.call(service.refresh)
    first_read = client.get("/api/v1/hints", headers=auth_headers).json()
    second_read = client.get("/api/v1/hints", headers=auth_headers).json()
    assert first_read == second_read and len(first_read["hints"]) == 1
    hint = first_read["hints"][0]
    assert hint["kind"] == "arrival_delivery" and first_read["next_id"] == hint["id"]
    assert "private-synthetic" not in json.dumps(first_read)
    assert (
        client.get(f"/api/v1/hints?after_id={hint['id']}", headers=auth_headers).json()["hints"]
        == []
    )
    assert first_read["feed_id"]


@pytest.mark.parametrize(
    "case", ["snapshot", "gap", "invalid_llm", "stale_checkpoint", "disconnected"]
)
def test_no_hint_from_snapshot_gap_unconfirmed_clock_or_invalid_model(
    client, auth_headers, monkeypatch, case
):
    service = setup(client, monkeypatch)
    client.app.state.telemetry.status = "disconnected" if case == "disconnected" else "connected"
    client.portal.call(
        partial(
            hint_context,
            snapshot=case == "snapshot",
            gap=case == "gap",
            invalid_llm=case == "invalid_llm",
        )
    )
    if case == "stale_checkpoint":

        async def old():
            async with base.async_session() as session, session.begin():
                row = await session.get(TelemetryCheckpoint, 1)
                row.last_seen = naive(NOW - timedelta(hours=1))

        client.portal.call(old)
    client.portal.call(service.refresh)
    assert client.get("/api/v1/hints", headers=auth_headers).json()["hints"] == []


def test_concurrent_metadata_and_telemetry_writes_do_not_break_disabled_collector(client):
    async def scenario():
        service = client.app.state.suggestions
        collector = client.app.state.telemetry
        for _ in range(10):
            await asyncio.gather(service.refresh(), collector.store.gap("SYNTHETIC_CONCURRENT"))
        assert collector.status == "disabled" and service.status == "disabled"

    client.portal.call(scenario)


@pytest.mark.parametrize("case", ["bad_order", "old_context", "unselected_source"])
def test_context_order_retention_and_source_policy(client, auth_headers, monkeypatch, case):
    service = setup(client, monkeypatch)
    client.app.state.telemetry.status = "connected"
    client.portal.call(hint_context)

    async def alter():
        from sqlalchemy import select

        async with base.async_session() as session, session.begin():
            if case == "bad_order":
                rows = list(
                    (
                        await session.scalars(
                            select(SensorHistory).order_by(SensorHistory.id.desc()).limit(2)
                        )
                    ).all()
                )
                rows[0].observed_at = naive(NOW - timedelta(seconds=10))
                rows[0].ha_timestamp = naive(NOW - timedelta(seconds=30))
                rows[1].observed_at = naive(NOW - timedelta(seconds=20))
            else:
                row = await session.scalar(
                    select(NotificationRaw).order_by(NotificationRaw.id.desc()).limit(1)
                )
                if case == "old_context":
                    row.created_at = naive(NOW - timedelta(days=2))
                else:
                    row.app_name = "private.unselected.bank"

    client.portal.call(alter)
    client.portal.call(service.refresh)
    assert client.get("/api/v1/hints", headers=auth_headers).json()["hints"] == []


def test_arrival_bounce_with_new_event_does_not_spam_within_hour(client, auth_headers, monkeypatch):
    service = setup(client, monkeypatch)
    client.app.state.telemetry.status = "connected"
    client.portal.call(hint_context)
    client.portal.call(service.refresh)
    first_feed = client.get("/api/v1/hints", headers=auth_headers).json()
    client.portal.call(hint_context)
    client.portal.call(service.refresh)
    assert client.get("/api/v1/hints", headers=auth_headers).json() == first_feed


def test_hint_retention_cap_and_ids_remain_monotonic(client, monkeypatch):
    from sqlalchemy import func, select

    from app.db.models import LocalHint

    service = setup(client, monkeypatch)
    client.portal.call(hint_context)

    async def fill():
        async with base.async_session() as session, session.begin():
            notification_id = await session.scalar(select(NotificationRaw.id).limit(1))
            session.add_all(
                [
                    LocalHint(
                        config_key=service.analytics.config_key,
                        presence_event_id=10000 + i,
                        notification_id=notification_id,
                        kind="arrival_delivery",
                        created_at=naive(NOW),
                    )
                    for i in range(1005)
                ]
            )

    client.portal.call(fill)
    client.portal.call(service.refresh)

    async def verify():
        async with base.async_session() as session, session.begin():
            assert await session.scalar(select(func.count()).select_from(LocalHint)) == 1000
            latest = await session.scalar(select(func.max(LocalHint.id)))
            row = await session.get(LocalHint, latest)
            row.created_at = naive(NOW - timedelta(days=8))
        return latest

    latest = client.portal.call(verify)
    client.portal.call(service.refresh)

    async def check():
        async with base.async_session() as session, session.begin():
            assert await session.get(LocalHint, latest) is None
            await session.execute(delete(LocalHint))
            row = LocalHint(
                config_key=service.analytics.config_key,
                presence_event_id=99999,
                notification_id=1,
                kind="arrival_delivery",
                created_at=naive(NOW),
            )
            session.add(row)
            await session.flush()
            assert row.id > latest

    client.portal.call(check)
