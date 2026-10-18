import asyncio
import json
from contextlib import suppress
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core import clock
from app.core.config import Settings, settings
from app.db import base
from app.db.models import NotificationRaw
from app.services.llm.engine import LLMError
from app.services.notification import worker as module
from app.services.notification.extraction import ExtractedNotification, parse_extraction
from app.services.notification.processor import validate_result
from app.services.notification.worker import NotificationWorker


class Engine:
    def __init__(self):
        self.status = "not_loaded"
        self.load_task = None
        self.release = asyncio.Event()
        self.release.set()
        self.boot_error = None
        self.modes = []
        self.calls = 0
        self.cancelled = 0
        self.closed = False

    def start(self):
        async def boot():
            self.status = "loading"
            await self.release.wait()
            self.status = self.boot_error or "ready"

        self.load_task = asyncio.create_task(boot())

    async def close(self):
        self.closed = True
        if self.load_task and not self.load_task.done():
            self.load_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.load_task

    async def load(self):
        self.status = "ready"

    async def generate(self, messages, *, schema):
        self.calls += 1
        mode = self.modes.pop(0) if self.modes else "success"
        if mode == "hold":
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
        if mode == "timeout":
            self.status = "LLM_TIMEOUT"
            raise LLMError("LLM_TIMEOUT")
        if mode == "context":
            raise LLMError("LLM_CONTEXT_EXCEEDED")
        content = (
            json.dumps(
                {
                    "category": "delivery",
                    "priority": "high",
                    "subject": "Курьер",
                    "location": None,
                    "service": "Ozon",
                    "time_expression": "через 15 минут",
                }
            )
            if mode == "success"
            else "private-invalid-native-response"
        )
        return SimpleNamespace(content=content, finish_reason="stop")


@pytest.fixture
def model(monkeypatch):
    from app import main

    engine = Engine()
    monkeypatch.setattr(settings, "notification_processor", "llm")
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "notification_processing_timeout_seconds", 0.1)
    monkeypatch.setattr(settings, "notification_shutdown_seconds", 0.1)
    monkeypatch.setattr(main, "LocalLLMEngine", lambda: engine)
    monkeypatch.setattr(module, "POLL_SECONDS", 0.01)
    return engine


@pytest.fixture
def llm_client(model, client):
    yield client
    client.portal.call(client.app.state.notification_worker.stop)


def post(client, headers):
    response = client.post(
        "/api/v1/notifications",
        headers=headers,
        json={
            "app_name": "ru.ozon.app.android",
            "title": "Курьер",
            "text": "Курьер Ozon приедет через 15 минут",
            "timestamp": clock.iso_utc(clock.utcnow()),
            "event_id": str(uuid4()),
        },
    )
    assert response.status_code == 201
    assert response.json()["processed_data"] is None
    return response.json()["id"]


def wait(client, row_id, status):
    async def poll():
        async with asyncio.timeout(3):
            while True:
                async with base.async_session() as session:
                    row = await session.get(NotificationRaw, row_id)
                    if row.processing_status == status:
                        return row
                await asyncio.sleep(0.005)

    return client.portal.call(poll)


def test_llm_result_persists_and_filters_without_home_action(
    llm_client, model, auth_headers, ha_mock
):
    client = llm_client
    row_id = post(client, auth_headers)
    row = wait(client, row_id, "processed")
    parsed = json.loads(row.extracted_data_json)
    assert row.category == "delivery" and row.processing_attempts == 1
    assert parsed["action_authorized"] is False and parsed["time"]["resolution"] == "exact"
    assert parsed["entities"]["service"] == "Ozon"
    response = client.get(f"/api/v1/notifications/{row_id}", headers=auth_headers).json()
    assert response["processed_data"] == parsed and response["category"] == "delivery"
    assert (
        client.get("/api/v1/notifications?category=delivery", headers=auth_headers).json()["total"]
        == 1
    )
    assert (
        client.get("/api/v1/notifications?category=noise", headers=auth_headers).json()["total"]
        == 0
    )
    client.portal.call(client.app.state.notification_worker.stop)
    restarted = NotificationWorker(llm=model)
    client.app.state.notification_worker = restarted
    client.portal.call(restarted.start)
    client.portal.call(asyncio.sleep, 0.03)
    assert model.calls == 1
    assert not [request for request in ha_mock.requests if request.method == "POST"]


@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("invalid", "LLM_BAD_RESPONSE"),
        ("timeout", "LLM_TIMEOUT"),
        ("hold", "PROCESSOR_TIMEOUT"),
        ("context", "LLM_CONTEXT_EXCEEDED"),
    ],
)
def test_failed_inference_does_not_block_next_event(
    model, llm_client, auth_headers, ha_mock, mode, error
):
    model.modes = [mode, "success"]
    first, second = post(llm_client, auth_headers), post(llm_client, auth_headers)
    failed = wait(llm_client, first, "failed")
    ready = wait(llm_client, second, "processed")
    assert failed.processing_error_code == error and failed.category is None
    assert failed.extracted_data_json is None and ready.category == "delivery"
    assert model.calls == 2
    assert model.cancelled == int(mode == "hold")
    assert not [request for request in ha_mock.requests if request.method == "POST"]


@pytest.fixture
def loading_model(model):
    model.release.clear()
    return model


@pytest.fixture
def loading_client(loading_model, client):
    yield client
    client.portal.call(client.app.state.notification_worker.stop)


def test_model_startup_does_not_consume_attempts_or_processing_budget(
    loading_client, model, auth_headers
):
    row_id = post(loading_client, auth_headers)
    loading_client.portal.call(asyncio.sleep, 0.15)

    async def read():
        async with base.async_session() as session:
            return await session.get(NotificationRaw, row_id)

    row = loading_client.portal.call(read)
    assert row.processing_status == "pending" and row.processing_attempts == 0
    assert loading_client.app.state.notification_worker.status == "waiting_model"
    assert loading_client.get("/api/v1/health").json()["llm_status"] == "loading"
    loading_client.portal.call(model.release.set)
    assert wait(loading_client, row_id, "processed").processing_attempts == 1


def test_unavailable_model_preserves_pending_and_basic_core(loading_client, model, auth_headers):
    model.boot_error = "LLM_MODEL_MISSING"
    row_id = post(loading_client, auth_headers)
    loading_client.portal.call(model.release.set)
    loading_client.portal.call(asyncio.sleep, 0.05)
    assert loading_client.app.state.notification_worker.status == "model_unavailable"
    page = loading_client.get("/api/v1/notifications", headers=auth_headers).json()
    row = next(item for item in page["items"] if item["id"] == row_id)
    assert row["processing_status"] == "pending" and row["processing_attempts"] == 0
    assert model.calls == 0


def test_uncertain_claim_recovers_even_when_model_becomes_unavailable(
    llm_client, model, auth_headers, monkeypatch
):
    worker = llm_client.app.state.notification_worker
    original = worker.claim

    async def uncertain(row_id):
        await original(row_id)
        model.status = "LLM_MODEL_MISSING"
        raise SQLAlchemyError("synthetic-uncertain-claim")

    monkeypatch.setattr(worker, "claim", uncertain)
    row_id = post(llm_client, auth_headers)

    async def poll():
        async with asyncio.timeout(3):
            while worker.status != "model_unavailable":
                await asyncio.sleep(0.01)

    llm_client.portal.call(poll)
    row = llm_client.get(f"/api/v1/notifications/{row_id}", headers=auth_headers).json()
    assert row["processing_status"] == "pending" and row["processing_attempts"] == 1
    assert row["processing_error_code"] == "PROCESSING_INTERRUPTED"
    assert model.calls == 0


def test_forged_constructed_result_is_revalidated_before_commit():
    from app.schemas import NotificationIn

    notification = NotificationIn(
        app_name="ru.ozon.app.android",
        title="Курьер",
        text="Курьер",
        timestamp="2026-10-17T00:00:00Z",
    )
    value = parse_extraction(
        json.dumps(
            {
                "category": "delivery",
                "priority": "default",
                "subject": "Курьер",
                "location": None,
                "service": None,
                "time_expression": None,
            }
        ),
        notification,
        "UTC",
    )
    fake = ExtractedNotification.model_construct(
        **{**value.model_dump(), "action_authorized": True}
    )
    with pytest.raises(ValidationError):
        validate_result(fake)


@pytest.mark.parametrize("zone", ["Mars/Test", "../UTC", ""])
def test_unknown_notification_timezone_rejected(zone):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, notification_timezone=zone)


def test_llm_mode_does_not_enable_llm_implicitly(monkeypatch):
    monkeypatch.setattr(settings, "notification_processor", "llm")
    monkeypatch.setattr(settings, "llm_enabled", False)
    assert NotificationWorker(llm=Engine()).processor is None
