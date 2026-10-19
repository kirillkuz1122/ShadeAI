import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_api_key
from app.db.base import get_session
from app.db.models import AutomationDecision, AutomationRule, AutomationRun
from app.services.suggestions.service import SuggestionError, action
from app.services.telemetry.store import iso

router = APIRouter(
    prefix="/automations", tags=["automations"], dependencies=[Depends(verify_api_key)]
)
Session = Annotated[AsyncSession, Depends(get_session)]
RuleId = Annotated[str, Path(pattern=r"^aut_[0-9a-f]{32}$")]
Status = Literal["pending", "accepted", "rejected", "disabled", "needs_review"]


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    decision: Literal["accept", "reject", "disable"]
    version: int = Field(ge=1, le=1_000_000_000)
    target_entity: str | None = Field(default=None, max_length=255, pattern=r"^light\.[a-z0-9_]+$")

    approval_scope: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )

    @model_validator(mode="after")
    def target(self):
        if (self.decision == "accept") != (self.target_entity is not None):
            raise ValueError("Конкретная цель нужна только для принятия предложения")
        if self.decision != "accept" and self.approval_scope is not None:
            raise ValueError("Контекст согласия нужен только для принятия")
        return self


def payload(rule, service, sources, executor=None):
    try:
        trigger = json.loads(rule.trigger_json)
        group = "будням" if trigger["day_group"] == "weekdays" else "выходным"
        what = (
            "Включать свет при приходе"
            if trigger["kind"] == "arrival_home"
            else "Выключать свет при уходе"
        )
        return {
            "id": rule.id,
            "source_habit_id": rule.source_habit_id,
            "name": f"{what} по {group}",
            "status": rule.status,
            "version": rule.version,
            "trigger": trigger,
            "action": action(rule),
            "evidence": json.loads(rule.evidence_json),
            "confidence": rule.confidence,
            "source_current": service.valid(rule, sources),
            "approval_valid": service.approved(rule, sources),
            "enabled": service.approved(rule, sources),
            "executable": bool(executor and executor.enabled and service.approved(rule, sources)),
            "executor_status": executor.status if executor else "disabled",
            "execution_policy": service.execution_scope,
            "approval_scope": service.consent_scope(rule.profile_key),
            "created_at": iso(rule.created_at),
            "updated_at": iso(rule.updated_at),
        }
    except (ValueError, KeyError, TypeError):
        raise HTTPException(503, {"code": "SUGGESTIONS_INVALID_SNAPSHOT"}) from None


@router.get("")
async def list_rules(
    request: Request,
    session: Session,
    status: Annotated[Status | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
    offset: Annotated[int, Query(ge=0, le=200)] = 0,
) -> dict:
    service = request.app.state.suggestions
    filters = [AutomationRule.status == status] if status else []
    async with session.begin():
        total = await session.scalar(
            select(func.count()).select_from(AutomationRule).where(*filters)
        )
        rows = list(
            (
                await session.scalars(
                    select(AutomationRule)
                    .where(*filters)
                    .order_by(AutomationRule.created_at.desc(), AutomationRule.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
        _, sources = await service.source_context(session)
    return {
        "automations": [
            payload(row, service, sources, request.app.state.automation_executor) for row in rows
        ],
        "total": total,
        "allowed_targets": list(service.allowed),
        "status": service.status,
        "executor_status": request.app.state.automation_executor.status,
    }


@router.post("/refresh")
async def refresh(request: Request) -> dict:
    try:
        await request.app.state.suggestions.refresh()
    except (SQLAlchemyError, ValueError, KeyError, TypeError):
        raise HTTPException(503, {"code": "SUGGESTIONS_UNAVAILABLE"}) from None
    return {"status": request.app.state.suggestions.status}


@router.get("/runs")
async def runs(
    request: Request,
    session: Session,
    before_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
) -> dict:
    query = select(AutomationRun).order_by(AutomationRun.id.desc()).limit(limit)
    if before_id is not None:
        query = query.where(AutomationRun.id < before_id)
    rows = list((await session.scalars(query)).all())
    return {
        "status": request.app.state.automation_executor.status,
        "runs": [
            {
                "id": row.id,
                "rule_id": row.rule_id,
                "state": row.state,
                "reason": row.reason,
                "target_entity": row.target_entity,
                "service": row.service,
                "created_at": iso(row.created_at),
                "due_at": iso(row.due_at),
                "started_at": iso(row.started_at),
                "finished_at": iso(row.finished_at),
                "event_id": row.event_id,
                "cancellable": row.state == "pending",
            }
            for row in rows
        ],
    }


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: Annotated[int, Path(ge=1)], request: Request) -> dict:
    try:
        await request.app.state.automation_executor.cancel(run_id)
    except SuggestionError as error:
        raise HTTPException(error.status, {"code": error.code}) from None
    except SQLAlchemyError:
        raise HTTPException(503, {"code": "AUTOMATION_RUN_UNAVAILABLE"}) from None
    return {"status": "cancelled"}


@router.get("/{rule_id}")
async def detail(rule_id: RuleId, request: Request, session: Session) -> dict:
    service = request.app.state.suggestions
    async with session.begin():
        row = await session.get(AutomationRule, rule_id)
        if row is None:
            raise HTTPException(404, {"code": "AUTOMATION_NOT_FOUND"})
        _, sources = await service.source_context(session)
        history = list(
            (
                await session.scalars(
                    select(AutomationDecision)
                    .where(AutomationDecision.rule_id == rule_id)
                    .order_by(AutomationDecision.id.desc())
                    .limit(20)
                )
            ).all()
        )
    return {
        **payload(row, service, sources, request.app.state.automation_executor),
        "history": [
            {
                "id": item.id,
                "decision": item.decision,
                "version": item.version,
                "target_entity": item.target_entity,
                "created_at": iso(item.created_at),
            }
            for item in history
        ],
    }


@router.post("/{rule_id}/decision")
async def decide(rule_id: RuleId, body: Decision, request: Request, session: Session) -> dict:
    service = request.app.state.suggestions
    try:
        await service.decide(
            rule_id, body.decision, body.version, body.target_entity, body.approval_scope
        )
    except SuggestionError as error:
        raise HTTPException(error.status, {"code": error.code}) from None
    except SQLAlchemyError:
        raise HTTPException(503, {"code": "SUGGESTIONS_UNAVAILABLE"}) from None
    async with session.begin():
        row = await session.get(AutomationRule, rule_id)
        _, sources = await service.source_context(session)
    return payload(row, service, sources, request.app.state.automation_executor)
