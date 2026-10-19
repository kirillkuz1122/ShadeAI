"""TASK-26: настоящий HTTP Core -> синтетический HA-замок, без железа/LLM."""

import argparse
import asyncio
import json
import os
import secrets
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx
from check_telemetry import start_server, stop_server
from fastapi import FastAPI, Request

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))
ENTITY = "lock.synthetic_delivery"


async def scenario(folder):
    fake = FastAPI()
    control = dict(commands=0, timeout=False)
    owner, keypad, ha_token = (secrets.token_urlsafe(32) for _ in range(3))

    def state():
        from app.core import clock

        return dict(
            entity_id=ENTITY,
            state="unlocked",
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

    @fake.post("/api/services/lock/unlock")
    async def unlock(request: Request):
        assert request.headers["Authorization"] == "Bearer " + ha_token
        assert await request.json() == {"entity_id": ENTITY}
        control["commands"] += 1
        if control["timeout"]:
            await asyncio.sleep(1)
        return [state()]

    fake_server, fake_task, port = await start_server(fake)
    os.environ.clear()
    os.environ.update(
        SHADE_API_KEY=owner,
        DB_URL=f"sqlite+aiosqlite:///{folder / 'synthetic.db'}",
        HA_BASE_URL=f"http://127.0.0.1:{port}",
        HA_TOKEN=ha_token,
        HA_TIMEOUT_SECONDS="0.2",
        HA_TELEMETRY_ENTITIES="[]",
        LLM_ENABLED="false",
        NOTIFICATION_PROCESSOR="disabled",
        ACCESS_ENABLED="true",
        ACCESS_ALLOWED_LOCKS=json.dumps([ENTITY]),
        ACCESS_KEYPAD_TOKEN=keypad,
        LOG_DIR=str(folder / "logs"),
    )
    from sqlalchemy import update

    from app.core import clock
    from app.db import base
    from app.db.models import NotificationRaw
    from app.main import create_app
    from app.services.notification.extraction import (
        ExtractedEntities,
        ExtractedNotification,
        ExtractedTime,
    )

    original_clock = clock.utcnow
    now = original_clock()
    clock.utcnow = lambda: now
    result = dict(synthetic=True, native_llm=False, hardware=False, adapter="shade_keypad")
    pending_id = None
    pending_pin = None
    pins = []
    try:
        for cycle in range(2):
            app = create_app()
            server, task, core_port = await start_server(app)
            try:
                async with httpx.AsyncClient(
                    base_url=f"http://127.0.0.1:{core_port}",
                    headers={"Authorization": "Bearer " + owner},
                    trust_env=False,
                    timeout=5,
                ) as http:
                    key_headers = {"Authorization": "Bearer " + keypad}

                    async def verify(pin, headers=key_headers):
                        return await http.post(
                            "/api/v1/access/keypad/verify",
                            headers=headers,
                            json=dict(entity_id=ENTITY, pin=pin),
                        )

                    if cycle:
                        old = (await http.get("/api/v1/access/grants/" + pending_id)).json()
                        assert old["state"] == "revoked"
                        assert (await verify(pending_pin)).status_code in {403, 429}
                        assert control["commands"] == 2
                        result["restart_revokes_without_replay"] = "PASS"
                        continue

                    async def create(index):
                        body = dict(
                            app_name="ru.ozon.app.android",
                            title="Доставка",
                            text=f"Синтетическая посылка {index}",
                            timestamp=clock.iso_utc(clock.utcnow()),
                            priority="default",
                            event_id=str(uuid4()),
                        )
                        receipt = await http.post("/api/v1/notifications", json=body)
                        assert receipt.status_code == 201
                        source = receipt.json()["id"]
                        parsed = ExtractedNotification(
                            category="delivery",
                            priority="default",
                            intent="delivery_event",
                            entities=ExtractedEntities(
                                subject="Посылка", location=None, service=None
                            ),
                            time=ExtractedTime(
                                source=None, timezone="UTC", at=None, date=None, resolution="absent"
                            ),
                        )
                        async with base.async_session() as session, session.begin():
                            await session.execute(
                                update(NotificationRaw)
                                .where(NotificationRaw.id == source)
                                .values(
                                    processing_status="processed",
                                    is_processed=1,
                                    category="delivery",
                                    extracted_data_json=parsed.model_dump_json(),
                                )
                            )
                        page = (await http.get("/api/v1/access")).json()
                        issue = dict(
                            notification_id=source,
                            entity_id=ENTITY,
                            duration_minutes=1,
                            policy_scope=page["policy_scope"],
                            confirmed=True,
                            delivery_checked=True,
                        )
                        response = await http.post("/api/v1/access/grants", json=issue)
                        assert response.status_code == 200, response.status_code
                        grant = response.json()
                        pins.append(grant["pin"])
                        repeated = await http.post("/api/v1/notifications", json=body)
                        assert repeated.json()["id"] == source
                        again = (await http.post("/api/v1/access/grants", json=issue)).json()
                        assert again["id"] == grant["id"] and again["pin"] is None
                        return grant

                    assert (
                        await verify("123456", {"Authorization": "Bearer " + owner})
                    ).status_code == 401
                    assert (
                        await http.get("/api/v1/access", headers=key_headers)
                    ).status_code == 401
                    grant = await create(1)
                    assert control["commands"] == 0
                    assert (await verify(grant["pin"])).json()["state"] == "used"
                    assert (await verify(grant["pin"])).status_code == 403
                    assert control["commands"] == 1
                    revoked = await create(2)
                    assert (
                        await http.post(
                            "/api/v1/access/grants/" + revoked["id"] + "/revoke", json={}
                        )
                    ).json()["state"] == "revoked"
                    assert (await verify(revoked["pin"])).status_code == 403
                    expired = await create(3)
                    now += timedelta(seconds=61)
                    assert (await verify(expired["pin"])).status_code == 403
                    unknown = await create(4)
                    control["timeout"] = True
                    assert (await verify(unknown["pin"])).json()["state"] == "unknown"
                    control["timeout"] = False
                    assert (await verify(unknown["pin"])).status_code in {403, 429}
                    assert control["commands"] == 2
                    assert (
                        await http.post(
                            "/api/v1/access/grants/" + unknown["id"] + "/revoke", json={}
                        )
                    ).status_code == 409
                    assert (
                        await http.post(
                            "/api/v1/access/grants/" + unknown["id"] + "/revoke",
                            json={"checked": True},
                        )
                    ).json()["state"] == "revoked"
                    pending = await create(5)
                    pending_id, pending_pin = pending["id"], pending["pin"]
                    for file in [*folder.glob("synthetic.db*"), *folder.glob("logs/*")]:
                        data = file.read_bytes()
                        assert not any(pin.encode() in data for pin in pins)
                    result.update(
                        one_time_owner_only="PASS",
                        notification_dedupe="PASS",
                        expiry_and_revoke="PASS",
                        timeout_unknown_no_retry="PASS",
                        no_plain_pin_in_db_logs="PASS",
                        separate_key_permissions="PASS",
                    )
            finally:
                await stop_server(server, task)
        result["synthetic_ha_unlocks"] = control["commands"]
        return result
    finally:
        clock.utcnow = original_clock
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
    with tempfile.TemporaryDirectory(prefix="task26-http-", dir=CORE / ".pytest_cache") as folder:
        os.chdir(folder)
        try:
            result = asyncio.run(scenario(Path(folder)))
        finally:
            os.chdir(previous)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
