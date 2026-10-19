import asyncio
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import ClientDisconnect

from app.api.deps import verify_api_key
from app.services.voice.audio import MAX_AUDIO_BYTES
from app.services.voice.errors import VoiceError

router = APIRouter(prefix="/voice", tags=["voice"], dependencies=[Depends(verify_api_key)])
Identity = Annotated[
    str, Path(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
]


class TextInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    request_id: str
    text: str = Field(min_length=1, max_length=512)


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    policy_scope: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: bool

    @field_validator("confirmed")
    @classmethod
    def explicit(cls, value):
        if value is not True:
            raise ValueError("Нужно подтверждение")
        return value


def identity(value):
    try:
        if UUID(value).version != 4 or str(UUID(value)) != value:
            raise ValueError
        return value
    except (ValueError, TypeError, AttributeError):
        raise VoiceError("VOICE_BAD_REQUEST_ID") from None


async def bounded_body(request, limit):
    body = bytearray()
    async with asyncio.timeout(5):
        async for chunk in request.stream():
            if len(body) + len(chunk) > limit:
                raise VoiceError("VOICE_BODY_TOO_LARGE", 413)
            body.extend(chunk)
    return bytes(body)


def fail(error):
    if isinstance(error, VoiceError):
        return HTTPException(error.status, {"code": error.code})
    if isinstance(error, TimeoutError):
        return HTTPException(408, {"code": "VOICE_UPLOAD_TIMEOUT"})
    return HTTPException(503, {"code": "VOICE_UNAVAILABLE"})


@router.get("")
async def descriptor(request: Request):
    try:
        return await request.app.state.voice.descriptor()
    except SQLAlchemyError as error:
        raise fail(error) from None


@router.post("")
async def prepare(request: Request):
    service = request.app.state.voice
    try:
        service.enabled()
        if service.lock.locked():
            raise VoiceError("VOICE_BUSY", 409)
        async with service.lock:
            content_type = request.headers.get("content-type", "").split(";")[0].lower()
            if content_type == "audio/wav":
                request_id = identity(request.headers.get("x-request-id"))
                data = await bounded_body(request, MAX_AUDIO_BYTES)
                source = "wav"
            elif content_type == "application/json":
                data = await bounded_body(request, 8192)
                try:
                    body = TextInput.model_validate(json.loads(data))
                except (ValidationError, ValueError, UnicodeError, RecursionError):
                    raise VoiceError("VOICE_BAD_INPUT") from None
                request_id = identity(body.request_id)
                data, source = body.text.encode("utf-8"), "manual_text"
            else:
                raise VoiceError("VOICE_UNSUPPORTED_MEDIA", 415)
            return await service.prepare(request_id, data, source)
    except ClientDisconnect:
        raise HTTPException(408, {"code": "VOICE_UPLOAD_INTERRUPTED"}) from None
    except (VoiceError, SQLAlchemyError, TimeoutError) as error:
        raise fail(error) from None


@router.get("/{request_id}")
async def state(request_id: Identity, request: Request):
    try:
        return await request.app.state.voice.get(request_id)
    except (VoiceError, SQLAlchemyError) as error:
        raise fail(error) from None


@router.post("/{request_id}/confirm")
async def confirm(request_id: Identity, body: Confirmation, request: Request):
    try:
        return await request.app.state.voice.confirm(request_id, body.policy_scope)
    except (VoiceError, SQLAlchemyError) as error:
        raise fail(error) from None


@router.post("/{request_id}/cancel")
async def cancel(request_id: Identity, request: Request):
    try:
        return await request.app.state.voice.cancel(request_id)
    except (VoiceError, SQLAlchemyError) as error:
        raise fail(error) from None
