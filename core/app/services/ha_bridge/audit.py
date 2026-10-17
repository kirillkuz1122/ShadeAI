import json
import logging
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.db.models import EventLog
from app.services.ha_bridge.client import HAClient, HAError

logger = logging.getLogger("shade.audit")
COMMAND_EVENTS = {"command_requested", "command_executed", "command_failed", "command_interrupted"}
PAYLOAD_KEYS = {"request_id", "entity_id", "domain", "service", "status", "error_code", "outcome"}


def event_cutoff():
    return clock.utcnow() - timedelta(days=settings.event_retention_days)


def safe_payload(raw: str) -> dict:
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError):
        return {}
    if not isinstance(value, dict):
        return {}
    # Произвольные старые params/ответы/тексты в API журнала не выдаются.
    return {
        key: item
        for key, item in value.items()
        if key in PAYLOAD_KEYS
        and (item is None or isinstance(item, str))
        and (item is None or len(item) <= 255)
    }


async def maintain_events(session: AsyncSession, *, recover: bool = False) -> None:
    await session.execute(delete(EventLog).where(EventLog.timestamp < event_cutoff()))
    if recover:
        last_id = 0
        while True:
            rows = list(
                await session.scalars(
                    select(EventLog)
                    .where(
                        EventLog.event_type == "command_requested",
                        EventLog.id > last_id,
                        EventLog.source == "home_assistant",
                    )
                    .order_by(EventLog.id)
                    .limit(256)
                )
            )
            if not rows:
                break
            for row in rows:
                last_id = row.id
                payload = safe_payload(row.payload_json)
                payload.update(status="unknown", outcome="unknown", error_code="CORE_RESTARTED")
                row.event_type = "command_interrupted"
                row.payload_json = json.dumps(payload)
    await session.commit()


async def execute_command(
    session: AsyncSession, client: HAClient, domain: str, service: str, entity_id: str, params: dict
) -> dict:
    payload = dict(
        request_id=str(uuid4()),
        entity_id=entity_id,
        domain=domain,
        service=service,
        status="pending",
        error_code=None,
        outcome="unknown",
    )
    row = EventLog(
        timestamp=clock.utcnow(),
        source="home_assistant",
        event_type="command_requested",
        payload_json=json.dumps(payload),
    )
    try:
        session.add(row)
        await session.commit()
    except SQLAlchemyError:
        await session.rollback()
        raise HTTPException(503, {"code": "AUDIT_UNAVAILABLE", "outcome": "not_sent"}) from None
    event_id = row.id
    failure = None
    result = None
    try:
        result = await client.call_service(domain, service, entity_id, params)
    except HAError as exc:
        failure = exc
    completed = clock.utcnow()
    payload.update(
        status="failed" if failure else "success",
        error_code=failure.code if failure else None,
        outcome=failure.outcome if failure else "accepted",
    )
    event_type = "command_failed" if failure else "command_executed"
    try:
        saved = await session.execute(
            update(EventLog)
            .where(EventLog.id == event_id)
            .values(timestamp=completed, event_type=event_type, payload_json=json.dumps(payload))
        )
        if saved.rowcount != 1:
            raise SQLAlchemyError("Audit row missing")
        await session.commit()
    except SQLAlchemyError:
        await session.rollback()
        logger.error("command event_id=%s outcome=unknown code=AUDIT_FINALIZATION_FAILED", event_id)
        raise HTTPException(
            503,
            {
                "code": "AUDIT_FINALIZATION_FAILED",
                "event_id": event_id,
                "outcome": payload["outcome"],
            },
        ) from None
    logger.info(
        "command event_id=%s status=%s code=%s",
        event_id,
        payload["status"],
        payload["error_code"] or "none",
    )
    if failure:
        raise HTTPException(
            failure.status_code,
            {"code": failure.code, "event_id": event_id, "outcome": failure.outcome},
        ) from None
    new_state = None
    try:
        new_state = (await client.get_state(entity_id)).state
    except HAError:
        pass
    return {
        "status": "success",
        "entity_id": entity_id,
        "new_state": new_state,
        "state_observed": new_state is not None,
        "executed_at": clock.iso_utc(completed),
        "event_id": event_id,
        "result": result,
    }
