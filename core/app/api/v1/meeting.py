import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_api_key
from app.core import clock
from app.db.base import get_session
from app.db.models import CalendarEvent, MeetingLease, MeetingLog, MeetingPlan
from app.services.suggestions.service import SuggestionError
from app.services.telemetry.store import iso, naive

router = APIRouter(prefix="/calendar", tags=["meeting"], dependencies=[Depends(verify_api_key)])
Session = Annotated[AsyncSession, Depends(get_session)]
EventId = Annotated[str, Path(pattern=r"^cal_[0-9a-f]{32}$")]


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    decision: Literal["approve", "disable"]
    event_revision: int = Field(ge=1)
    policy_scope: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    targets: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def check_scope(self):
        if self.decision == "approve" and (self.policy_scope is None or not self.targets):
            raise ValueError("Нужны показанные условия и цели")
        if self.decision == "disable" and (self.policy_scope is not None or self.targets):
            raise ValueError("Выключение не выбирает цели")
        return self


class Acknowledge(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    generation: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    checked: bool

    @field_validator("checked")
    @classmethod
    def require_checked(cls, value):
        if value is not True:
            raise ValueError("Подтвердите ручную проверку устройства")
        return value


def lease_payload(row):
    return dict(
        entity_id=row.entity_id,
        generation=row.generation,
        state=row.state,
        reason=row.reason,
        members=json.loads(row.members_json),
        event_id=row.event_id,
        updated_at=iso(row.updated_at),
    )


@router.get("/events/{event_id}/meeting")
async def view(event_id: EventId, request: Request, session: Session):
    service = request.app.state.meeting
    async with session.begin():
        event = await session.get(CalendarEvent, event_id)
        if event is None or event.config_key != service.calendar.config_key:
            raise HTTPException(404, {"code": "CALENDAR_EVENT_NOT_FOUND"})
        plan = await session.get(MeetingPlan, event_id)
        meta = await service.calendar.snapshot(session)
        scope = service.scope(event)
        targets = json.loads(plan.targets_json) if plan else []
        eligible = not meta["stale"] and service.eligible(event, naive(clock.utcnow()))
        approved = bool(
            plan
            and plan.status == "approved"
            and plan.policy_scope == scope
            and eligible
            and all(t in service.allowed for t in targets)
        )
    return dict(
        event_id=event_id,
        event_revision=event.revision,
        policy=service.policy,
        policy_scope=scope,
        eligible=eligible,
        stale=meta["stale"],
        starts_at=iso(event.starts_at),
        ends_at=iso(event.ends_at),
        status=plan.status if plan else "not_approved",
        targets=targets,
        approval_valid=approved,
        started_targets=json.loads(plan.started_json) if plan else [],
    )


@router.post("/events/{event_id}/meeting")
async def decide(event_id: EventId, body: Decision, request: Request):
    try:
        await request.app.state.meeting.decide(
            event_id, body.decision, body.event_revision, body.policy_scope, body.targets
        )
    except SuggestionError as error:
        raise HTTPException(error.status, {"code": error.code}) from None
    except SQLAlchemyError:
        raise HTTPException(503, {"code": "MEETING_UNAVAILABLE"}) from None
    return {"status": "approved" if body.decision == "approve" else "disabled"}


@router.get("/meeting")
async def state(request: Request, session: Session):
    service = request.app.state.meeting
    async with session.begin():
        plans = list(
            (
                await session.scalars(
                    select(MeetingPlan).order_by(MeetingPlan.starts_at).limit(200)
                )
            ).all()
        )
        leases = list(
            (
                await session.scalars(
                    select(MeetingLease).order_by(MeetingLease.entity_id).limit(100)
                )
            ).all()
        )
        logs = list(
            (
                await session.scalars(select(MeetingLog).order_by(MeetingLog.id.desc()).limit(50))
            ).all()
        )
    return dict(
        status=service.status,
        policy=service.policy,
        plans=[
            dict(
                event_id=row.event_id,
                event_revision=row.event_revision,
                status=row.status,
                targets=json.loads(row.targets_json),
                starts_at=iso(row.starts_at),
                ends_at=iso(row.ends_at),
            )
            for row in plans
        ],
        leases=[lease_payload(row) for row in leases],
        history=[
            dict(
                id=row.id,
                entity_id=row.entity_id,
                generation=row.generation,
                state=row.state,
                reason=row.reason,
                event_id=row.event_id,
                created_at=iso(row.created_at),
            )
            for row in logs
        ],
    )


@router.post("/meeting/leases/{entity_id}/ack")
async def ack(
    entity_id: Annotated[str, Path(pattern=r"^switch\.[a-z0-9_]+$", max_length=255)],
    body: Acknowledge,
    request: Request,
):
    try:
        await request.app.state.meeting.acknowledge(entity_id, body.generation)
    except SuggestionError as error:
        raise HTTPException(error.status, {"code": error.code}) from None
    except SQLAlchemyError:
        raise HTTPException(503, {"code": "MEETING_UNAVAILABLE"}) from None
    return {"status": "acknowledged"}
