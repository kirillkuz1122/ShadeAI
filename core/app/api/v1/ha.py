from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_api_key
from app.api.ha_deps import get_ha_client
from app.db.base import get_session
from app.services.ha_bridge.audit import execute_command
from app.services.ha_bridge.client import HAClient
from app.services.ha_bridge.models import HAAction

router = APIRouter(prefix="/ha", tags=["home-assistant"], dependencies=[Depends(verify_api_key)])


@router.post("/action", deprecated=True)
async def ha_action(
    action: HAAction,
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[HAClient, Depends(get_ha_client)],
) -> dict:
    return await execute_command(
        session, client, action.domain, action.service, action.entity_id, action.data or {}
    )
