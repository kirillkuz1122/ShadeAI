"""Синтетический API только для OS-проверки Android24, без БД/моделей/HA."""

import hashlib
from datetime import UTC, datetime, timedelta

import uvicorn
from fastapi import FastAPI, HTTPException, Request

API_KEY = "task24-synthetic-emulator-key-00000001"
app = FastAPI()
state = {
    "revision": 1,
    "due": datetime.now(UTC) + timedelta(hours=1),
    "cancelled": False,
    "validation": 0,
    "acks": 0,
    "decisions": 0,
    "approved": False,
    "source": "a" * 64,
}
EVENT = "cal_" + "a" * 32
GENERATION = "11111111-1111-1111-1111-111111111111"
POLICY = {
    "version": 1,
    "enabled": True,
    "allowed_targets": ["switch.dnd"],
    "max_duration_seconds": 28800,
}


def stamp(value):
    return value.isoformat().replace("+00:00", "Z")


def item():
    due = state["due"]
    return dict(
        id="rmd_" + hashlib.sha256(str(state["revision"]).encode()).hexdigest()[:32],
        event_id=EVENT,
        event_revision=state["revision"],
        due_at=stamp(due),
        expires_at=stamp(due + timedelta(seconds=300)),
        due=due <= datetime.now(UTC),
    )


def page():
    return dict(
        version=1,
        policy_scope="b" * 64,
        source_id=state["source"],
        enabled=True,
        configured=True,
        stale=False,
        server_time=stamp(datetime.now(UTC)),
        timezone="UTC",
        lead_minutes=10,
        grace_seconds=300,
    )


@app.middleware("http")
async def auth(request: Request, next):
    if (
        request.url.path.startswith("/api/v1/")
        and not request.url.path.endswith("/health")
        and request.headers.get("authorization") != "Bearer " + API_KEY
    ):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": "denied"}, status_code=401)
    return await next(request)


@app.get("/api/v1/health")
async def health():
    return dict(
        status="degraded",
        uptime=1,
        ha_connected=False,
        llm_status="not_loaded",
        db_size="0 B",
        db_connected=True,
        ha_status="not_configured",
        services={},
    )


@app.get("/api/v1/notifications")
async def notifications():
    return dict(total=0, items=[])


@app.post("/checks/arm")
async def arm(seconds: int = 35):
    assert 20 <= seconds <= 180
    state.update(
        revision=state["revision"] + 1,
        due=datetime.now(UTC) + timedelta(seconds=seconds),
        cancelled=False,
    )
    return item()


@app.post("/checks/cancel")
async def cancel():
    state["cancelled"] = True
    return {"ok": True}


@app.get("/checks/state")
async def status():
    return {k: v for k, v in state.items() if k != "due"}


@app.get("/api/v1/calendar/reminders")
async def schedule():
    return page() | dict(
        overflow=False, reminders=[] if state["cancelled"] else [item()]
    )


@app.get("/api/v1/calendar/reminders/{identity}")
async def validate(identity: str):
    state["validation"] += 1
    if (
        state["cancelled"]
        or identity != item()["id"]
        or datetime.now(UTC) >= state["due"] + timedelta(seconds=300)
    ):
        raise HTTPException(404)
    return page() | dict(reminder=item())


@app.get("/api/v1/calendar/events")
async def events():
    due = state["due"]
    event = dict(
        id=EVENT,
        summary="Синтетическая встреча AVD24",
        location=None,
        starts_at=stamp(due + timedelta(minutes=10)),
        ends_at=stamp(due + timedelta(minutes=20)),
        start_date=None,
        end_date=None,
        all_day=False,
        status="confirmed",
        busy=True,
        revision=state["revision"],
        updated_at=stamp(datetime.now(UTC)),
    )
    return dict(
        status="ready",
        configured=True,
        stale=False,
        timezone="UTC",
        last_success=None,
        events=[event],
        total=1,
    )


@app.get("/api/v1/calendar/events/{identity}/meeting")
async def meeting(identity: str):
    return dict(
        event_id=EVENT,
        event_revision=state["revision"],
        policy=POLICY,
        policy_scope="c" * 64,
        eligible=True,
        stale=False,
        starts_at=stamp(state["due"]),
        ends_at=stamp(state["due"] + timedelta(hours=1)),
        status="approved" if state["approved"] else "not_approved",
        targets=["switch.dnd"] if state["approved"] else [],
        approval_valid=state["approved"],
        started_targets=[],
    )


@app.post("/api/v1/calendar/events/{identity}/meeting")
async def decision(identity: str, request: Request):
    body = await request.json()
    if body["decision"] == "approve":
        assert body["policy_scope"] == "c" * 64 and body["targets"] == ["switch.dnd"]
    state["decisions"] += 1
    state["approved"] = body["decision"] == "approve"
    return {"status": "approved" if state["approved"] else "disabled"}


@app.get("/api/v1/calendar/meeting")
async def meeting_state():
    return dict(
        status="ready",
        policy=POLICY,
        plans=[],
        leases=[
            dict(
                entity_id="switch.dnd",
                generation=GENERATION,
                state="completed" if state["acks"] else "unknown",
                reason="CORE_RESTARTED",
                members=[],
                event_id=1,
                updated_at=stamp(datetime.now(UTC)),
            )
        ],
        history=[],
    )


@app.post("/api/v1/calendar/meeting/leases/{entity}/ack")
async def ack(entity: str, request: Request):
    body = await request.json()
    assert body == dict(generation=GENERATION, checked=True)
    state["acks"] += 1
    return {"status": "acknowledged"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8002, access_log=False, log_level="warning")
