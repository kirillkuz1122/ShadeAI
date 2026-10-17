import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from app.core import clock
from app.core.config import settings
from app.db import base
from app.db.models import NotificationRaw
from app.services.notification.maintenance import cleanup

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(clock, "utcnow", lambda: NOW)


def payload(**changes):
    return (
        dict(
            app_name="ru.ozon.app.android",
            title="Доставка",
            text="Курьер прибудет вечером",
            timestamp=clock.iso_utc(clock.utcnow()),
            priority="default",
        )
        | changes
    )


def post(client, auth_headers, **changes):
    return client.post("/api/v1/notifications", headers=auth_headers, json=payload(**changes))


def database_rows(client):
    async def read():
        async with base.async_session() as session:
            return list(await session.scalars(select(NotificationRaw).order_by(NotificationRaw.id)))

    return client.portal.call(read)


def test_store_detail_and_real_status(client, auth_headers):
    result = post(client, auth_headers, event_id=str(uuid4()))
    assert result.status_code == 201
    assert result.json()["status"] == "stored"
    assert result.json()["processed_data"] is None
    detail = client.get(f"/api/v1/notifications/{result.json()['id']}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["text"] == payload()["text"]
    assert detail.json()["category"] is None
    assert detail.json()["status"] == "stored"
    assert detail.json()["priority"] == "default"
    assert detail.json()["created_at"] == clock.iso_utc(NOW)
    assert detail.json()["event_id"] is not None
    assert client.get("/api/v1/notifications/999", headers=auth_headers).status_code == 404
    assert client.get("/api/v1/notifications/1").status_code == 401
    assert (
        client.get(
            "/api/v1/notifications/999999999999999999999999", headers=auth_headers
        ).status_code
        == 422
    )


@pytest.mark.parametrize("event_id", [None, "181d66f4-5401-4e97-b7be-059da5fc6282"])
def test_retries_are_idempotent_and_normalize_timezone(client, auth_headers, event_id):
    body = payload(event_id=event_id)
    first = client.post("/api/v1/notifications", headers=auth_headers, json=body)
    second = client.post(
        "/api/v1/notifications",
        headers=auth_headers,
        json=body | {"timestamp": "2026-10-17T17:00:00+05:00"},
    )
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["status"] == "duplicate"
    assert len(database_rows(client)) == 1


def test_conflicting_event_id_and_distinct_events(client, auth_headers):
    event_id = str(uuid4())
    first = post(client, auth_headers, event_id=event_id)
    conflict = post(client, auth_headers, event_id=event_id, text="Изменённое событие")
    assert conflict.status_code == 409
    another = post(client, auth_headers, event_id=str(uuid4()))
    assert another.status_code == 201
    assert another.json()["id"] != first.json()["id"]
    assert len(database_rows(client)) == 2


def test_parallel_retries_create_one_row(client, auth_headers):
    event_id = str(uuid4())
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(
            pool.map(lambda _: post(client, auth_headers, event_id=event_id), range(6))
        )
    assert sorted(r.status_code for r in responses) == [200] * 5 + [201]
    assert len({r.json()["id"] for r in responses}) == 1
    assert len(database_rows(client)) == 1


def test_pagination_total_and_category_filter(client, auth_headers):
    ids = [post(client, auth_headers, text=f"Событие {n}").json()["id"] for n in range(5)]
    page = client.get("/api/v1/notifications?limit=2&offset=1", headers=auth_headers).json()
    assert page["total"] == 5
    assert [item["id"] for item in page["items"]] == [ids[3], ids[2]]
    empty = client.get("/api/v1/notifications?offset=99", headers=auth_headers).json()
    assert empty == {"items": [], "total": 5}

    async def categorize():
        async with base.async_session() as session:
            await session.execute(
                update(NotificationRaw)
                .where(NotificationRaw.id.in_(ids[:3]))
                .values(category="delivery")
            )
            await session.commit()

    client.portal.call(categorize)
    filtered = client.get(
        "/api/v1/notifications?category=delivery&limit=1&offset=1", headers=auth_headers
    ).json()
    assert filtered["total"] == 3
    assert filtered["items"][0]["id"] == ids[1]


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=201", "offset=-1", "offset=1000001", "category=bad%20category", "limit=abc"],
)
def test_query_validation(client, auth_headers, query):
    assert client.get("/api/v1/notifications?" + query, headers=auth_headers).status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        {"app_name": "bad package"},
        {"title": "x" * 513},
        {"text": "x" * 8193},
        {"title": " ", "text": "\n"},
        {"timestamp": "2026-10-17"},
        {"timestamp": "2026-10-17T12:00:00"},
        {"timestamp": "2026-02-30T12:00:00Z"},
        {"timestamp": "2026-10-17T12:00:00+00:99"},
        {"timestamp": 1792238400},
        {"timestamp": "2026-10-17T12:06:00Z"},
        {"priority": "urgent"},
        {"event_id": "not-uuid"},
        {"text": 123},
        {"unknown": "secret"},
    ],
)
def test_body_validation_does_not_echo_input(client, auth_headers, changes, caplog):
    body = payload(**changes)
    response = client.post("/api/v1/notifications", headers=auth_headers, json=body)
    assert response.status_code == 422
    assert "input" not in response.text
    assert payload()["text"] not in response.text + caplog.text
    assert not database_rows(client)


@pytest.mark.parametrize("body", [b'{"text":"private-secret",', b"x" * 65537])
def test_invalid_json_and_request_size(client, auth_headers, body, caplog):
    response = client.post(
        "/api/v1/notifications",
        headers=auth_headers | {"Content-Type": "application/json"},
        content=body,
    )
    assert response.status_code == (413 if len(body) > 65536 else 422)
    assert "private-secret" not in response.text + caplog.text
    assert not database_rows(client)


def test_chunked_request_limit(client, auth_headers):
    response = client.post(
        "/api/v1/notifications", headers=auth_headers, content=iter([b"x" * 20000] * 4)
    )
    assert response.status_code == 413
    assert not database_rows(client)


@pytest.mark.parametrize(
    "changes",
    [
        {"app_name": "com.sberbank.mobile", "text": "Код банка 839174"},
        {"app_name": "org.telegram.messenger", "text": "Личная переписка СЕКРЕТ"},
        {"app_name": "com.unknown.app", "text": "Личная переписка СЕКРЕТ"},
        {"text": "Код подтверждения 839174"},
        {"title": "Verification code", "text": "839174"},
        {"text": "Одноразовый пароль: 839174"},
    ],
)
def test_private_payload_is_never_persisted(client, auth_headers, changes, caplog):
    response = post(client, auth_headers, **changes)
    assert response.status_code == 200
    assert response.json()["status"] == "skipped"
    assert response.json()["id"] is None
    assert response.json()["reason"] == "privacy_policy"
    assert "839174" not in response.text + caplog.text
    assert "СЕКРЕТ" not in response.text + caplog.text
    assert not database_rows(client)
    from pathlib import Path

    from sqlalchemy.engine import make_url

    db_path = Path(make_url(settings.db_url).database)
    for path in db_path.parent.glob(db_path.name + "*"):
        assert b"839174" not in path.read_bytes()
        assert "СЕКРЕТ".encode() not in path.read_bytes()


def test_private_apps_cannot_be_enabled_accidentally(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "notification_allowed_apps", ["com.sberbank.mobile"])
    assert post(client, auth_headers, app_name="com.sberbank.mobile").json()["status"] == "skipped"


def test_retention_hides_then_deletes_and_never_reuses_ids(client, auth_headers, monkeypatch):
    first = post(client, auth_headers)
    first_id = first.json()["id"]
    monkeypatch.setattr(clock, "utcnow", lambda: NOW + timedelta(days=31))
    assert client.get("/api/v1/notifications", headers=auth_headers).json()["total"] == 0
    assert client.get(f"/api/v1/notifications/{first_id}", headers=auth_headers).status_code == 404
    expired = post(client, auth_headers, timestamp=clock.iso_utc(NOW))
    assert expired.json()["reason"] == "expired"
    client.portal.call(cleanup)
    assert not database_rows(client)
    fresh = post(client, auth_headers)
    assert fresh.status_code == 201
    assert fresh.json()["id"] > first_id


def test_legacy_cleanup_filters_and_deduplicates_before_exposure(client, auth_headers):
    async def seed():
        async with base.async_session() as session:
            bodies = [
                payload(),
                payload(),
                payload(app_name="org.telegram.messenger"),
                payload(text="Код входа 839174"),
                payload(text="x" * 8193),
            ]
            for body in bodies:
                session.add(
                    NotificationRaw(
                        **body,
                        created_at=NOW,
                        extracted_data_json=json.dumps({"legacy_secret": "839174"}),
                        is_processed=1,
                    )
                )
            await session.commit()

    client.portal.call(seed)
    assert client.get("/api/v1/notifications", headers=auth_headers).json()["total"] == 0
    client.portal.call(cleanup)
    rows = database_rows(client)
    assert len(rows) == 1
    assert rows[0].payload_hash
    assert rows[0].extracted_data_json is None
    assert rows[0].is_processed == 0
    assert client.get("/api/v1/notifications", headers=auth_headers).json()["total"] == 1
    assert post(client, auth_headers).json()["status"] == "duplicate"


def test_retention_configuration_bounds(monkeypatch):
    from pydantic import ValidationError

    from app.core.config import Settings

    monkeypatch.setenv("NOTIFICATION_RETENTION_DAYS", "0")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_periodic_cleanup_retries_without_logging_payload(monkeypatch, caplog):
    from app.services.notification import maintenance

    calls = 0

    async def sleep(seconds):
        nonlocal calls
        assert seconds == 3600
        calls += 1
        if calls == 3:
            raise asyncio.CancelledError

    job = AsyncMock(side_effect=[RuntimeError("private-secret-839174"), None])
    monkeypatch.setattr(maintenance, "asyncio", SimpleNamespace(sleep=sleep))
    monkeypatch.setattr(maintenance, "cleanup", job)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(maintenance.cleanup_loop())
    assert job.await_count == 2
    assert "Очистка уведомлений не выполнена" in caplog.text
    assert "private-secret-839174" not in caplog.text
