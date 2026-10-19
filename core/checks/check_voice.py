"""TASK-25: настоящий HTTP Core/HA, WAV и синтетический STT без модели."""

import argparse
import asyncio
import io
import json
import os
import secrets
import sys
import tempfile
import wave
from pathlib import Path
from uuid import uuid4

import httpx
from check_telemetry import start_server, stop_server
from fastapi import FastAPI, Request

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))
ENTITY = "light.synthetic_voice"
TEXT = "включи свет на кухне"


def wave_data(frames=4000):
    output = io.BytesIO()
    with wave.open(output, "wb") as file:
        file.setparams((1, 2, 16000, frames, "NONE", ""))
        file.writeframes(b"\x01" * (frames * 2))
    return output.getvalue()


async def scenario(folder):
    fake = FastAPI()
    control = dict(commands=0, state="off", timeout=False)
    key, token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)

    def state():
        from app.core import clock

        return dict(
            entity_id=ENTITY,
            state=control["state"],
            attributes={},
            last_changed=clock.iso_utc(clock.utcnow()),
            last_updated=clock.iso_utc(clock.utcnow()),
        )

    @fake.get("/api/")
    async def ping():
        return {"message": "API running."}

    @fake.get("/api/states/{entity}")
    async def current(entity: str):
        assert entity == ENTITY
        return state()

    @fake.post("/api/services/light/{action}")
    async def command(action: str, request: Request):
        assert action in {"turn_on", "turn_off"} and await request.json() == {"entity_id": ENTITY}
        assert request.headers["Authorization"] == "Bearer " + token
        control["commands"] += 1
        control["state"] = "on" if action == "turn_on" else "off"
        if control["timeout"]:
            await asyncio.sleep(1)
        return [state()]

    fake_server, fake_task, port = await start_server(fake)
    os.environ.clear()
    os.environ.update(
        SHADE_API_KEY=key,
        DB_URL=f"sqlite+aiosqlite:///{folder / 'synthetic.db'}",
        HA_BASE_URL=f"http://127.0.0.1:{port}",
        HA_TOKEN=token,
        HA_TIMEOUT_SECONDS="0.2",
        HA_TELEMETRY_ENTITIES="[]",
        LLM_ENABLED="false",
        NOTIFICATION_PROCESSOR="disabled",
        VOICE_ENABLED="true",
        VOICE_TARGETS=json.dumps({"свет на кухне": ENTITY}),
        LOG_DIR=str(folder / "logs"),
    )
    from app.db import base
    from app.main import create_app
    from app.services.voice.audio import read_pcm
    from app.services.voice.engine import Transcription

    class SyntheticSTT:
        calls = 0

        def configured(self):
            return True

        async def transcribe(self, audio):
            read_pcm(audio)
            self.calls += 1
            return Transcription(TEXT, 0.99)

        async def close(self):
            pass

    result = dict(synthetic=True, native_stt=False, native_llm=False, hardware=False)
    identity = str(uuid4())
    unknown = str(uuid4())
    pending = str(uuid4())
    try:
        for cycle in range(2):
            app = create_app()
            server, task, core_port = await start_server(app)
            engine = SyntheticSTT()
            app.state.voice.engine = engine
            try:
                async with httpx.AsyncClient(
                    base_url=f"http://127.0.0.1:{core_port}",
                    headers={"Authorization": "Bearer " + key},
                    trust_env=False,
                    timeout=8,
                ) as http:
                    assert (
                        await http.get("/api/v1/voice", headers={"Authorization": "Bearer invalid"})
                    ).status_code == 401
                    descriptor = (await http.get("/api/v1/voice")).json()
                    assert descriptor["enabled"] and descriptor["stt_available"]
                    headers = {"Content-Type": "audio/wav", "X-Request-ID": identity}
                    if cycle:
                        stored = (await http.get("/api/v1/voice/" + identity)).json()
                        assert stored["state"] == "accepted" and stored["transcription"] is None
                        assert (
                            await http.post(
                                "/api/v1/voice/" + identity + "/confirm",
                                json={"policy_scope": stored["policy_scope"], "confirmed": True},
                            )
                        ).json()["state"] == "accepted"
                        assert (await http.get("/api/v1/voice/" + unknown)).json()[
                            "state"
                        ] == "unknown"
                        assert (await http.get("/api/v1/voice/" + pending)).json()[
                            "state"
                        ] == "cancelled"
                        assert control["commands"] == 2 and engine.calls == 0
                        result["restart_no_replay"] = "PASS"
                        continue
                    plan = (
                        await http.post("/api/v1/voice", headers=headers, content=wave_data())
                    ).json()
                    assert (
                        plan["state"] == "pending"
                        and plan["transcription"] == TEXT
                        and control["commands"] == 0
                    )
                    assert (
                        await http.post("/api/v1/voice", headers=headers, content=wave_data())
                    ).json()["transcription"] is None and engine.calls == 1
                    assert (
                        await http.post("/api/v1/voice", headers=headers, content=wave_data(4001))
                    ).status_code == 409
                    body = dict(policy_scope=plan["policy_scope"], confirmed=True)
                    done = (
                        await http.post("/api/v1/voice/" + identity + "/confirm", json=body)
                    ).json()
                    assert (
                        done["state"] == "accepted"
                        and done["state_observed"]
                        and done["new_state"] == "on"
                    )
                    assert (
                        await http.post("/api/v1/voice/" + identity + "/confirm", json=body)
                    ).json()["state"] == "accepted" and control["commands"] == 1
                    control["timeout"] = True
                    uncertain = (
                        await http.post(
                            "/api/v1/voice",
                            headers={"Content-Type": "audio/wav", "X-Request-ID": unknown},
                            content=wave_data(),
                        )
                    ).json()
                    unknown_body = dict(policy_scope=uncertain["policy_scope"], confirmed=True)
                    assert (
                        await http.post("/api/v1/voice/" + unknown + "/confirm", json=unknown_body)
                    ).json()["state"] == "unknown"
                    assert (
                        await http.post("/api/v1/voice/" + unknown + "/confirm", json=unknown_body)
                    ).json()["state"] == "unknown" and control["commands"] == 2
                    control["timeout"] = False
                    assert (
                        await http.post("/api/v1/voice", json=dict(request_id=pending, text=TEXT))
                    ).json()["state"] == "pending"
                    for datafile in folder.glob("synthetic.db*"):
                        assert (
                            TEXT.encode() not in datafile.read_bytes()
                            and b"RIFF" not in datafile.read_bytes()
                        )
                    result.update(
                        raw_wav_and_explicit_confirmation="PASS",
                        uuid_dedupe="PASS",
                        timeout_unknown_no_retry="PASS",
                        durable_without_audio_or_transcript="PASS",
                        authentication="PASS",
                    )
            finally:
                await stop_server(server, task)
        result["synthetic_ha_commands"] = control["commands"]
        return result
    finally:
        await stop_server(fake_server, fake_task)
        await base.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    if output.exists():
        parser.error("Существующий отчёт не перезаписывается")
    previous = Path.cwd()
    (CORE / ".pytest_cache").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="task25-http-", dir=CORE / ".pytest_cache") as folder:
        os.chdir(folder)
        try:
            result = asyncio.run(scenario(Path(folder)))
        finally:
            os.chdir(previous)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
