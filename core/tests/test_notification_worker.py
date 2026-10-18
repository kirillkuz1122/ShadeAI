import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.core import clock
from app.core.config import Settings, settings
from app.db import base
from app.db.models import NotificationRaw
from app.services.notification import worker as module
from app.services.notification.processor import ProcessingResult
from app.services.notification.worker import NotificationWorker

PRIVATE = "untrusted-private-processor-message-839174"


class Processor:
    def __init__(self):
        self.release = asyncio.Event()
        self.calls = []
        self.mode = "success"
        self.active = 0
        self.maximum = 0

    async def __call__(self, notification):
        self.calls.append(notification.text)
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        try:
            if self.mode in {"hold", "timeout"}:
                await self.release.wait()
            if self.mode == "raise":
                raise RuntimeError(PRIVATE)
            if self.mode == "invalid":
                return {"processor": "diagnostic", "raw": PRIVATE}
            return ProcessingResult(processor="diagnostic")
        finally:
            self.active -= 1


@pytest.fixture
def processor(monkeypatch):
    from app import main

    proc = Processor()
    monkeypatch.setattr(settings, "notification_queue_size", 3)
    monkeypatch.setattr(settings, "notification_shutdown_seconds", 0.1)
    monkeypatch.setattr(module, "POLL_SECONDS", 0.05)
    monkeypatch.setattr(main, "NotificationWorker", lambda: NotificationWorker(proc))
    return proc


@pytest.fixture
def worker_client(processor, client):
    yield client
    client.portal.call(client.app.state.notification_worker.stop)


@pytest.fixture
def diagnostic_settings(monkeypatch):
    monkeypatch.setattr(settings, "notification_processor", "diagnostic")


@pytest.fixture
def diagnostic_client(diagnostic_settings, client):
    return client


def test_explicit_diagnostic_mode(diagnostic_client, auth_headers):
    client = diagnostic_client
    row_id = post(client, auth_headers).json()["id"]
    row = wait_row(client, row_id, lambda row: row.processing_status == "processed")
    assert json.loads(row.extracted_data_json) == {"processor": "diagnostic", "llm": False}


def post(client, auth_headers, text="Синтетическое событие", **extra):
    return client.post(
        "/api/v1/notifications",
        headers=auth_headers,
        json={
            "app_name": "ru.ozon.app.android",
            "title": "Доставка",
            "text": text,
            "timestamp": clock.iso_utc(clock.utcnow()),
            "event_id": str(uuid4()),
            **extra,
        },
    )


def wait_row(client, row_id, condition, timeout=3):
    async def poll():
        async with asyncio.timeout(timeout):
            while True:
                async with base.async_session() as session:
                    row = await session.get(NotificationRaw, row_id)
                    if condition(row):
                        return row
                await asyncio.sleep(0.005)

    return client.portal.call(poll)


def call_sql(client, statement):
    async def apply():
        async with base.async_session() as session, session.begin():
            await session.execute(statement)

    client.portal.call(apply)


def restart(client, processor):
    old = client.app.state.notification_worker
    client.portal.call(old.stop)
    new = NotificationWorker(processor)
    client.app.state.notification_worker = new
    client.portal.call(new.start)
    return new


def test_disabled_preserves_pending_and_legacy_receipt(client, auth_headers):
    row_id = post(client, auth_headers).json()["id"]
    body = client.get(f"/api/v1/notifications/{row_id}", headers=auth_headers).json()
    assert body["status"] == "stored" and body["processing_status"] == "pending"
    assert body["processing_attempts"] == 0 and body["processed_data"] is None
    assert client.get("/api/v1/health").json()["services"]["notification_worker"] == "disabled"
    assert client.app.state.notification_worker.task is None


def test_success_is_durable_without_fake_analysis(worker_client, auth_headers, processor):
    client = worker_client
    response = post(client, auth_headers)
    row_id = response.json()["id"]
    assert response.json()["status"] == "stored" and response.json()["processed_data"] is None
    row = wait_row(client, row_id, lambda row: row.processing_status == "processed")
    assert row.processing_attempts == 1 and row.processing_finished_at >= row.processing_started_at
    body = client.get(f"/api/v1/notifications/{row_id}", headers=auth_headers).json()
    assert body["status"] == "processed" and body["category"] is None
    assert body["processed_data"] == {"processor": "diagnostic", "llm": False}
    assert body["processing_error_code"] is None
    assert len(processor.calls) == 1


def test_slow_processor_does_not_block_http_or_ha(worker_client, auth_headers, processor):
    client = worker_client
    processor.mode = "hold"
    row_id = post(client, auth_headers).json()["id"]
    wait_row(client, row_id, lambda row: row.processing_status == "processing")
    started = time.monotonic()
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/notifications", headers=auth_headers).status_code == 200
    assert (
        client.post(
            "/api/v1/devices/light.test/command", headers=auth_headers, json={"action": "turn_on"}
        ).status_code
        == 200
    )
    assert post(client, auth_headers, "Следующая запись").status_code == 201
    assert time.monotonic() - started < 2
    client.portal.call(processor.release.set)
    wait_row(client, row_id, lambda row: row.processing_status == "processed")


def test_bounded_ids_queue_and_single_consumer(worker_client, auth_headers, processor):
    client = worker_client
    worker = client.app.state.notification_worker
    processor.mode = "hold"
    first = post(client, auth_headers, "Первая").json()["id"]
    wait_row(client, first, lambda row: row.processing_status == "processing")
    ids = [post(client, auth_headers, f"Запись {i}").json()["id"] for i in range(12)]
    assert worker.queue.maxsize == 3 and worker.queue.qsize() <= 3
    client.portal.call(processor.release.set)
    wait_row(client, ids[-1], lambda row: row.processing_status == "processed", timeout=5)
    assert processor.maximum == 1 and len(processor.calls) == 13
    assert worker.queue.qsize() <= 3 and worker.queue._unfinished_tasks == 0
    assert all(isinstance(value, int) for value in worker.queue._queue)


@pytest.mark.parametrize(
    "mode,code",
    [("raise", "PROCESSOR_ERROR"), ("invalid", "INVALID_RESULT"), ("timeout", "PROCESSOR_TIMEOUT")],
)
def test_failures_are_safe_terminal_and_do_not_block_next(
    worker_client, auth_headers, processor, monkeypatch, mode, code
):
    client = worker_client
    processor.mode = mode
    monkeypatch.setattr(settings, "notification_processing_timeout_seconds", 0.05)
    row_id = post(client, auth_headers).json()["id"]
    row = wait_row(client, row_id, lambda row: row.processing_status == "failed")
    assert row.processing_error_code == code and row.extracted_data_json is None
    processor.mode = "success"
    next_id = post(client, auth_headers, "Следующая").json()["id"]
    wait_row(client, next_id, lambda row: row.processing_status == "processed")
    restart(client, processor)
    assert (
        wait_row(client, row_id, lambda row: row.processing_status == "failed").processing_attempts
        == 1
    )
    body = client.get(f"/api/v1/notifications/{row_id}", headers=auth_headers).json()
    assert body["status"] == "stored" and body["processing_error_code"] == code
    assert PRIVATE not in json.dumps(body)
    db = Path(make_url(settings.db_url).database)
    for path in [*db.parent.glob(db.name + "*"), *Path(settings.log_dir).glob("*")]:
        assert PRIVATE.encode() not in path.read_bytes()


def test_duplicate_does_not_reset_running_or_processed(worker_client, auth_headers, processor):
    client = worker_client
    processor.mode = "hold"
    event_id = str(uuid4())
    timestamp = clock.iso_utc(clock.utcnow())
    first = post(client, auth_headers, event_id=event_id, timestamp=timestamp).json()["id"]
    wait_row(client, first, lambda row: row.processing_status == "processing")
    assert (
        post(client, auth_headers, event_id=event_id, timestamp=timestamp).json()["status"]
        == "duplicate"
    )
    client.portal.call(processor.release.set)
    wait_row(client, first, lambda row: row.processing_status == "processed")
    assert (
        post(client, auth_headers, event_id=event_id, timestamp=timestamp).json()["status"]
        == "duplicate"
    )
    assert len(processor.calls) == 1


def test_shutdown_and_recovery_only_recompute_unfinished(worker_client, auth_headers, processor):
    client = worker_client
    done = post(client, auth_headers, "Готовая").json()["id"]
    wait_row(client, done, lambda row: row.processing_status == "processed")
    processor.mode = "hold"
    interrupted = post(client, auth_headers, "Прерванная").json()["id"]
    wait_row(client, interrupted, lambda row: row.processing_status == "processing")
    pending = post(client, auth_headers, "Ожидающая").json()["id"]
    client.portal.call(client.app.state.notification_worker.stop)
    assert wait_row(client, interrupted, lambda row: row.processing_status == "processing")
    processor.mode = "success"
    restart(client, processor)
    row = wait_row(client, pending, lambda row: row.processing_status == "processed")
    assert row.processing_attempts == 1
    assert (
        wait_row(
            client, interrupted, lambda row: row.processing_status == "processed"
        ).processing_attempts
        == 2
    )
    assert processor.calls.count("Готовая") == 1


def test_graceful_shutdown_finishes_inflight(worker_client, auth_headers, processor, monkeypatch):
    client = worker_client
    monkeypatch.setattr(settings, "notification_shutdown_seconds", 1)
    processor.mode = "hold"
    row_id = post(client, auth_headers).json()["id"]
    wait_row(client, row_id, lambda row: row.processing_status == "processing")

    async def stop():
        task = asyncio.create_task(client.app.state.notification_worker.stop())
        await asyncio.sleep(0.02)
        processor.release.set()
        await task

    client.portal.call(stop)
    assert wait_row(client, row_id, lambda row: row.processing_status == "processed")


def test_result_commit_failure_retries_without_recomputing(
    worker_client, auth_headers, processor, monkeypatch
):
    client = worker_client
    worker = client.app.state.notification_worker
    original = worker.finish
    attempts = 0

    async def finish(*args):
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise SQLAlchemyError(PRIVATE)
        await original(*args)

    monkeypatch.setattr(worker, "finish", finish)
    row_id = post(client, auth_headers).json()["id"]
    wait_row(client, row_id, lambda row: row.processing_status == "processed")
    assert attempts == 3 and len(processor.calls) == 1


def test_uncertain_claim_commit_recovers_in_same_process(
    worker_client, auth_headers, processor, monkeypatch
):
    client = worker_client
    worker = client.app.state.notification_worker
    original = worker.claim
    calls = 0

    async def claim(row_id):
        nonlocal calls
        work = await original(row_id)
        calls += 1
        if calls == 1:
            raise SQLAlchemyError(PRIVATE)
        return work

    monkeypatch.setattr(worker, "claim", claim)
    row_id = post(client, auth_headers).json()["id"]
    row = wait_row(client, row_id, lambda row: row.processing_status == "processed")
    assert row.processing_attempts == 2 and len(processor.calls) == 1


@pytest.mark.parametrize("removal", ["delete", "expire", "deselect"])
def test_result_cannot_resurrect_removed_data(
    worker_client, auth_headers, processor, monkeypatch, removal
):
    client = worker_client
    processor.mode = "hold"
    row_id = post(client, auth_headers).json()["id"]
    wait_row(client, row_id, lambda row: row.processing_status == "processing")
    if removal == "delete":
        call_sql(client, delete(NotificationRaw).where(NotificationRaw.id == row_id))
    elif removal == "expire":
        current = datetime.now(UTC)
        monkeypatch.setattr(clock, "utcnow", lambda: current + timedelta(days=31))
    else:
        monkeypatch.setattr(settings, "notification_allowed_apps", [])
    client.portal.call(processor.release.set)

    async def idle():
        async with asyncio.timeout(2):
            while client.app.state.notification_worker.status != "idle":
                await asyncio.sleep(0.005)

    client.portal.call(idle)
    assert client.get(f"/api/v1/notifications/{row_id}", headers=auth_headers).status_code == 404

    async def read():
        async with base.async_session() as session:
            return await session.get(NotificationRaw, row_id)

    row = client.portal.call(read)
    assert row is None or row.extracted_data_json is None


def test_privacy_checked_again_before_handler(worker_client, auth_headers, processor):
    client = worker_client
    processor.mode = "hold"
    first = post(client, auth_headers, "Первая").json()["id"]
    wait_row(client, first, lambda row: row.processing_status == "processing")
    private = post(client, auth_headers, "Вторая").json()["id"]
    call_sql(
        client,
        update(NotificationRaw)
        .where(NotificationRaw.id == private)
        .values(text="Код входа 839174"),
    )
    client.portal.call(processor.release.set)
    wait_row(client, private, lambda row: row is None)
    assert processor.calls == ["Первая"]


def test_filter_and_invalid_processing_status(worker_client, auth_headers):
    client = worker_client
    row_id = post(client, auth_headers).json()["id"]
    wait_row(client, row_id, lambda row: row.processing_status == "processed")
    assert (
        client.get(
            "/api/v1/notifications?processing_status=processed", headers=auth_headers
        ).json()["total"]
        == 1
    )
    assert (
        client.get("/api/v1/notifications?processing_status=failed", headers=auth_headers).json()[
            "total"
        ]
        == 0
    )
    response = client.get(
        "/api/v1/notifications?processing_status=secret-marker", headers=auth_headers
    )
    assert response.status_code == 422 and "secret-marker" not in response.text


@pytest.mark.parametrize(
    "changes",
    [
        {"notification_queue_size": 0},
        {"notification_queue_size": 257},
        {"notification_processor": "cloud"},
        {"notification_shutdown_seconds": 0},
        {"notification_processing_timeout_seconds": 301},
    ],
)
def test_queue_config_bounds(changes):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **changes)
