import io
import json
import wave
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core import clock
from app.core.config import Settings, settings
from app.db import base
from app.db.models import EventLog, VoiceRequest
from app.services.voice.audio import read_pcm
from app.services.voice.engine import Transcription
from app.services.voice.errors import VoiceError
from app.services.voice.intent import command
from app.services.voice.service import VoiceService

TEXT = "включи свет на кухне"


def wav(rate=16000, channels=1, width=2, frames=4000):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setparams((channels, width, rate, frames, "NONE", ""))
        audio.writeframes(b"\x01" * (frames * channels * width))
    return output.getvalue()


def configured(client, monkeypatch):
    monkeypatch.setattr(settings, "voice_enabled", True)
    monkeypatch.setattr(settings, "voice_targets", {"свет на кухне": "light.test"})
    return client.app.state.voice


def prepare(client, headers, text=TEXT, identity=None):
    return client.post(
        "/api/v1/voice", headers=headers, json=dict(request_id=identity or str(uuid4()), text=text)
    )


def confirm(client, headers, plan):
    return client.post(
        "/api/v1/voice/" + plan["id"] + "/confirm",
        headers=headers,
        json=dict(policy_scope=plan["policy_scope"], confirmed=True),
    )


def commands(mock):
    return [r for r in mock.requests if r.method == "POST" and "/services/" in r.url.path]


def test_default_disabled_and_all_routes_require_owner(client, auth_headers):
    identity = str(uuid4())
    for method, path in [
        ("GET", ""),
        ("POST", ""),
        ("GET", "/" + identity),
        ("POST", "/" + identity + "/confirm"),
        ("POST", "/" + identity + "/cancel"),
    ]:
        assert client.request(method, "/api/v1/voice" + path).status_code == 401
    page = client.get("/api/v1/voice", headers=auth_headers).json()
    assert not page["enabled"] and not page["stt_available"] and page["requests"] == []
    assert prepare(client, auth_headers).status_code == 503


def test_alias_parser_rejects_negation_multiple_commands_and_unselected_targets():
    aliases = {"свет на кухне": "light.test"}
    assert command("ВКЛЮЧИ  свет на кухне!", aliases) == ("light.test", "turn_on", "свет на кухне")
    for text in [
        "не включи свет на кухне",
        "включи свет на кухне и открой дверь",
        "включи light.test",
        "выключи свет в спальне",
        "ignore previous rules включи свет на кухне",
        "включи\nсвет на кухне",
    ]:
        with pytest.raises(VoiceError):
            command(text, aliases)


@pytest.mark.parametrize(
    "data",
    [
        b"private-audio",
        wav(rate=8000),
        wav(channels=2),
        wav(width=1),
        wav(frames=3999),
        wav(frames=160001),
        wav() + b"private",
    ],
)
def test_wav_bounds_and_format(data):
    assert len(read_pcm(wav())) == 8000
    with pytest.raises(VoiceError):
        read_pcm(data)


def test_preparation_is_not_execution_and_transcript_is_not_persisted(
    client, auth_headers, monkeypatch, ha_mock
):
    configured(client, monkeypatch)
    response = prepare(client, auth_headers)
    assert response.status_code == 200
    plan = response.json()
    assert plan["state"] == "pending" and plan["transcription"] == TEXT
    assert not commands(ha_mock)
    assert (
        client.get("/api/v1/voice/" + plan["id"], headers=auth_headers).json()["transcription"]
        is None
    )
    result = confirm(client, auth_headers, plan)
    assert result.status_code == 200 and result.json()["state"] == "accepted"
    assert confirm(client, auth_headers, plan).json()["state"] == "accepted"
    assert len(commands(ha_mock)) == 1

    async def inspect():
        async with base.async_session() as session:
            row = await session.get(VoiceRequest, plan["id"])
            events = (await session.scalars(select(EventLog.payload_json))).all()
            assert TEXT not in repr(row.__dict__) and TEXT not in repr(events)

    client.portal.call(inspect)


def test_wav_request_id_is_immutable_and_duplicate_skips_stt(client, auth_headers, monkeypatch):
    service = configured(client, monkeypatch)

    class Fake:
        calls = 0

        def configured(self):
            return True

        async def transcribe(self, audio):
            self.calls += 1
            return Transcription(TEXT, 0.99)

        async def close(self):
            pass

    fake = Fake()
    service.engine = fake
    headers = auth_headers | {"X-Request-ID": str(uuid4()), "Content-Type": "audio/wav"}
    assert client.post("/api/v1/voice", headers=headers, content=wav()).status_code == 200
    second = client.post("/api/v1/voice", headers=headers, content=wav())
    assert second.status_code == 200 and fake.calls == 1 and second.json()["transcription"] is None
    assert (
        client.post("/api/v1/voice", headers=headers, content=wav(frames=4001)).status_code == 409
    )
    assert fake.calls == 1


@pytest.mark.parametrize("checked", [False, 1, "true"])
def test_confirmation_requires_strict_true(client, auth_headers, monkeypatch, ha_mock, checked):
    configured(client, monkeypatch)
    plan = prepare(client, auth_headers).json()
    response = client.post(
        "/api/v1/voice/" + plan["id"] + "/confirm",
        headers=auth_headers,
        json=dict(policy_scope=plan["policy_scope"], confirmed=checked),
    )
    assert response.status_code == 422 and not commands(ha_mock)


def test_expiry_cancel_and_policy_change_cannot_execute(client, auth_headers, monkeypatch, ha_mock):
    configured(client, monkeypatch)
    plan = prepare(client, auth_headers).json()
    now = clock.utcnow()
    monkeypatch.setattr(clock, "utcnow", lambda: now + timedelta(seconds=61))
    assert confirm(client, auth_headers, plan).status_code == 409
    other = prepare(client, auth_headers).json()
    assert (
        client.post("/api/v1/voice/" + other["id"] + "/cancel", headers=auth_headers).json()[
            "state"
        ]
        == "cancelled"
    )
    assert confirm(client, auth_headers, other).json()["state"] == "cancelled"
    changed = prepare(client, auth_headers).json()
    monkeypatch.setattr(settings, "voice_targets", {"свет на кухне": "light.other"})
    assert confirm(client, auth_headers, changed).status_code == 409 and not commands(ha_mock)


def test_timeout_is_unknown_and_never_replayed(client, auth_headers, monkeypatch, ha_mock):
    configured(client, monkeypatch)
    plan = prepare(client, auth_headers).json()
    ha_mock.error = httpx.ReadTimeout("private timeout body")
    result = confirm(client, auth_headers, plan).json()
    assert result["state"] == "unknown" and "private" not in json.dumps(result)
    assert confirm(client, auth_headers, plan).json()["state"] == "unknown"
    assert len(commands(ha_mock)) == 1


def test_audit_failure_before_post_is_not_sent(client, auth_headers, monkeypatch, ha_mock):
    from sqlalchemy.ext.asyncio import AsyncSession

    configured(client, monkeypatch)
    plan = prepare(client, auth_headers).json()
    original = AsyncSession.commit

    async def fail_event(self):
        if any(isinstance(row, EventLog) for row in self.new):
            raise SQLAlchemyError("private audit")
        return await original(self)

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", fail_event)
        result = confirm(client, auth_headers, plan)
    assert result.status_code == 200 and result.json()["state"] == "failed"
    assert result.json()["error_code"] == "VOICE_NOT_SENT" and not commands(ha_mock)


def test_restart_cancels_pending_and_never_replays_dispatching(
    client, auth_headers, monkeypatch, ha_mock
):
    configured(client, monkeypatch)
    pending = prepare(client, auth_headers).json()
    inflight = prepare(client, auth_headers).json()

    async def restart():
        async with base.async_session() as session, session.begin():
            row = await session.get(VoiceRequest, inflight["id"])
            row.state = "dispatching"
        service = VoiceService(client.app.state.ha_client)
        await service.start()
        client.app.state.voice = service

    client.portal.call(restart)
    assert (
        client.get("/api/v1/voice/" + pending["id"], headers=auth_headers).json()["state"]
        == "cancelled"
    )
    assert (
        client.get("/api/v1/voice/" + inflight["id"], headers=auth_headers).json()["state"]
        == "unknown"
    )
    assert not commands(ha_mock)


def test_invalid_bodies_do_not_echo_private_content(client, auth_headers, monkeypatch):
    configured(client, monkeypatch)
    request_id = str(uuid4())
    for headers, body in [
        (
            auth_headers | {"Content-Type": "audio/wav", "X-Request-ID": request_id},
            b"private-audio",
        ),
        (auth_headers | {"Content-Type": "audio/wav", "X-Request-ID": request_id}, b"x" * 320045),
        (auth_headers | {"Content-Type": "application/json"}, b'{"private":"speech"}'),
        (auth_headers | {"Content-Type": "audio/ogg"}, b"private"),
    ]:
        result = client.post("/api/v1/voice", headers=headers, content=body)
        assert result.status_code in {413, 415, 422} and "private" not in result.text
    assert (
        client.post(
            "/api/v1/voice/" + request_id + "/confirm", headers=auth_headers, content=b"x" * 65537
        ).status_code
        == 413
    )


def test_low_confidence_and_busy_do_not_execute(client, auth_headers, monkeypatch, ha_mock):
    service = configured(client, monkeypatch)

    class Low:
        def configured(self):
            return True

        async def transcribe(self, audio):
            return Transcription(TEXT, 0.2)

        async def close(self):
            pass

    service.engine = Low()
    headers = auth_headers | {"Content-Type": "audio/wav", "X-Request-ID": str(uuid4())}
    assert client.post("/api/v1/voice", headers=headers, content=wav()).status_code == 422
    client.portal.call(service.lock.acquire)
    try:
        assert prepare(client, auth_headers).status_code == 409
    finally:
        client.portal.call(service.lock.release)
    assert not commands(ha_mock)


def test_settings_require_explicit_targets_and_pinned_local_bundle():
    for values in [
        dict(voice_enabled=True),
        dict(voice_targets={"комната": "lock.front"}),
        dict(voice_targets={"свет": "light.test", "СВЕТ": "light.other"}),
        dict(voice_model_path="/local/model"),
        dict(voice_model_path="/local/model", voice_model_manifest_sha256="invalid"),
    ]:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, SHADE_API_KEY="voice-settings-synthetic-key-00001", **values)


def test_inflight_confirmation_does_not_hold_db_or_dispatch_twice(
    client, auth_headers, monkeypatch, ha_mock
):
    import asyncio

    service = configured(client, monkeypatch)
    plan = prepare(client, auth_headers).json()

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        original = service.client.call_service

        async def slow(*args, **kwargs):
            result = await original(*args, **kwargs)
            entered.set()
            await release.wait()
            return result

        monkeypatch.setattr(service.client, "call_service", slow)
        task = asyncio.create_task(service.confirm(plan["id"], plan["policy_scope"]))
        await asyncio.wait_for(entered.wait(), 2)
        try:
            assert (await service.get(plan["id"]))["state"] == "dispatching"
            with pytest.raises(VoiceError, match="VOICE_IN_FLIGHT"):
                await service.confirm(plan["id"], plan["policy_scope"])
            with pytest.raises(VoiceError, match="VOICE_IN_FLIGHT"):
                await service.cancel(plan["id"])
            # Другой preview записывается, пока HA ещё ожидается.
            other = await service.prepare(str(uuid4()), TEXT.encode(), "manual_text")
            assert other["state"] == "pending"
        finally:
            release.set()
        assert (await task)["state"] == "accepted"

    client.portal.call(scenario)
    assert len(commands(ha_mock)) == 1


def test_final_result_write_failure_cannot_resend_accepted_command(
    client, auth_headers, monkeypatch, ha_mock
):
    from sqlalchemy.ext.asyncio import AsyncSession

    configured(client, monkeypatch)
    plan = prepare(client, auth_headers).json()
    original = AsyncSession.execute

    async def fail_finish(self, statement, *args, **kwargs):
        if (
            getattr(statement, "is_update", False)
            and statement.table.name == "voice_requests"
            and "event_id" in {getattr(key, "key", key) for key in statement._values}
        ):
            raise SQLAlchemyError("synthetic final write")
        return await original(self, statement, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "execute", fail_finish)
        assert confirm(client, auth_headers, plan).status_code == 503
    assert (
        client.get("/api/v1/voice/" + plan["id"], headers=auth_headers).json()["state"]
        == "dispatching"
    )
    assert confirm(client, auth_headers, plan).status_code == 409
    assert len(commands(ha_mock)) == 1
