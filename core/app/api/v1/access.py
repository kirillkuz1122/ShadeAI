import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import verify_api_key
from app.core.config import settings
from app.services.access.service import AccessError

router = APIRouter(prefix="/access", tags=["access"])
Identity = Annotated[str, Path(pattern=r"^[a-f0-9]{8}-[a-f0-9-]{27}$")]


class CreateGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    notification_id: int = Field(gt=0)
    entity_id: str = Field(pattern=r"^lock\.[a-z0-9_]{1,249}$")
    duration_minutes: int = Field(ge=1, le=15)
    policy_scope: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: bool
    delivery_checked: bool

    @field_validator("confirmed", "delivery_checked")
    @classmethod
    def consent(cls, value):
        if value is not True:
            raise ValueError("Нужно явное подтверждение")
        return value


class RevokeGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    checked: bool = False


class VerifyPIN(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    entity_id: str = Field(pattern=r"^lock\.[a-z0-9_]{1,249}$")
    pin: str = Field(pattern=r"^[0-9]{6}$", repr=False)


async def keypad_key(authorization: str | None = Header(default=None)):
    expected = settings.access_keypad_token
    actual = authorization.removeprefix("Bearer ") if authorization else ""
    if (
        not expected
        or expected == settings.api_key
        or not authorization
        or not authorization.startswith("Bearer ")
        or not actual.isascii()
        or not hmac.compare_digest(actual, expected)
    ):
        raise HTTPException(401, {"code": "ACCESS_KEYPAD_UNAUTHORIZED"})


def fail(error):
    if isinstance(error, AccessError):
        return HTTPException(error.status, {"code": error.code})
    return HTTPException(503, {"code": "ACCESS_UNAVAILABLE"})


@router.get("", dependencies=[Depends(verify_api_key)])
async def descriptor(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return await request.app.state.access.descriptor()
    except SQLAlchemyError as error:
        raise fail(error) from None


@router.post("/grants", dependencies=[Depends(verify_api_key)])
async def create(body: CreateGrant, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return await request.app.state.access.create(
            body.notification_id, body.entity_id, body.duration_minutes, body.policy_scope
        )
    except (AccessError, SQLAlchemyError) as error:
        raise fail(error) from None


@router.get("/grants/{grant_id}", dependencies=[Depends(verify_api_key)])
async def state(grant_id: Identity, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return await request.app.state.access.get(grant_id)
    except (AccessError, SQLAlchemyError) as error:
        raise fail(error) from None


@router.post("/grants/{grant_id}/revoke", dependencies=[Depends(verify_api_key)])
async def revoke(grant_id: Identity, body: RevokeGrant, request: Request):
    try:
        return await request.app.state.access.revoke(grant_id, body.checked)
    except (AccessError, SQLAlchemyError) as error:
        raise fail(error) from None


@router.post("/keypad/verify", dependencies=[Depends(keypad_key)])
async def verify(body: VerifyPIN, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        result = await request.app.state.access.verify(body.entity_id, body.pin)
        # Ограниченный ключ не читает источник/owner-историю/идентификаторы аудита.
        return {key: result[key] for key in ("state", "error_code", "new_state", "state_observed")}
    except (AccessError, SQLAlchemyError) as error:
        raise fail(error) from None
