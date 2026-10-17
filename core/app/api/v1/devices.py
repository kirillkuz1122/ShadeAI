from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_api_key
from app.api.ha_deps import get_ha_client
from app.core import clock
from app.db.base import get_session
from app.services.ha_bridge.audit import execute_command
from app.services.ha_bridge.client import HAClient, HAError
from app.services.ha_bridge.models import EntityId, HACommand, HAState, Name

router = APIRouter(prefix="/devices", tags=["devices"], dependencies=[Depends(verify_api_key)])
Client = Annotated[HAClient, Depends(get_ha_client)]


def normalize(state: HAState) -> dict:
    name = state.attributes.get("friendly_name")
    return dict(
        entity_id=state.entity_id,
        name=name if isinstance(name, str) and len(name) <= 255 else state.entity_id,
        state=state.state,
        type=state.entity_id.split(".")[0],
        attributes=state.attributes,
        last_changed=clock.iso_utc(state.last_changed),
        last_updated=clock.iso_utc(state.last_updated),
    )


@router.get("")
async def devices(client: Client, domain: Annotated[Name | None, Query()] = None) -> dict:
    try:
        states = await client.get_states()
    except HAError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code}) from None
    return {
        "devices": [
            normalize(state)
            for state in states
            if domain is None or state.entity_id.split(".")[0] == domain
        ]
    }


@router.get("/{entity_id}/state")
async def device_state(entity_id: EntityId, client: Client) -> dict:
    try:
        return normalize(await client.get_state(entity_id))
    except HAError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code}) from None


@router.post("/{entity_id}/command")
async def command(
    entity_id: EntityId,
    body: HACommand,
    client: Client,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    result = await execute_command(
        session, client, entity_id.split(".")[0], body.action, entity_id, body.params
    )
    result.pop("result")
    return result
