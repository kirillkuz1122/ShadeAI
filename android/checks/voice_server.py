"""Настоящий Core для UI25, синтетические STT/HA, отдельная временная БД."""

import json
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[2]
API_KEY = "task25-synthetic-emulator-key-00000001"
TEXT = "включи свет на кухне"


def main():
    previous = Path.cwd()
    cache = ROOT / "core/.pytest_cache"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="task25-android-", dir=cache) as folder:
        os.chdir(folder)
        os.environ.clear()
        os.environ.update(
            SHADE_API_KEY=API_KEY,
            DB_URL="sqlite+aiosqlite:///synthetic.db",
            HA_TOKEN="",
            HA_BASE_URL="http://127.0.0.1:1",
            VOICE_ENABLED="true",
            VOICE_TARGETS=json.dumps({"свет на кухне": "light.synthetic_voice"}),
            LLM_ENABLED="false",
            NOTIFICATION_PROCESSOR="disabled",
            LOG_DIR="./logs",
        )
        sys.path.insert(0, str(ROOT / "core"))
        from app.main import create_app
        from app.services.ha_bridge.client import HAError
        from app.services.ha_bridge.models import HAState
        from app.services.voice.audio import read_pcm
        from app.services.voice.engine import Transcription

        control = dict(mode="normal", stt_calls=0, commands=0, frames=[], state="off")

        class STT:
            def configured(self):
                return True

            async def transcribe(self, audio):
                pcm = read_pcm(audio)
                control["stt_calls"] += 1
                control["frames"].append(len(pcm) // 2)
                return Transcription(TEXT, 0.99)

            async def close(self):
                pass

        class HA:
            async def call_service(self, domain, action, entity, params):
                assert (domain, entity, params) == (
                    "light",
                    "light.synthetic_voice",
                    {},
                )
                control["commands"] += 1
                control["state"] = "on" if action == "turn_on" else "off"
                if control["mode"] == "unknown":
                    raise HAError("HA_TIMEOUT", 504, "unknown")
                return []

            async def get_state(self, entity):
                now = datetime.now(UTC).isoformat()
                return HAState(
                    entity_id=entity,
                    state=control["state"],
                    attributes={},
                    last_changed=now,
                    last_updated=now,
                )

        app = create_app()
        original = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(value):
            async with original(value):
                value.state.voice.engine = STT()
                value.state.voice.client = HA()
                yield

        app.router.lifespan_context = lifespan

        @app.middleware("http")
        async def denied(request: Request, next):
            if control["mode"] == "denied" and request.url.path.startswith(
                "/api/v1/voice"
            ):
                return JSONResponse(
                    {"detail": "private synthetic auth body"}, status_code=401
                )
            return await next(request)

        @app.get("/checks/state")
        async def state():
            return control

        @app.post("/checks/mode/{mode}")
        async def mode(mode: str):
            assert mode in {"normal", "unknown", "denied"}
            control["mode"] = mode
            return {"ok": True}

        try:
            uvicorn.run(
                app, host="127.0.0.1", port=8003, log_level="warning", access_log=False
            )
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    main()
