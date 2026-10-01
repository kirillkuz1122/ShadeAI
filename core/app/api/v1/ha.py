from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import verify_api_key
from app.services.ha_bridge.client import HAClient

router = APIRouter(prefix="/ha", tags=["home-assistant"], dependencies=[Depends(verify_api_key)])


class HAAction(BaseModel):
    domain: str
    service: str
    entity_id: str
    data: dict | None = None


@router.post("/action")
async def ha_action(action: HAAction) -> dict:
    client = HAClient()
    try:
        result = await client.call_service(
            action.domain, action.service, action.entity_id, action.data or {}
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Home Assistant unavailable: {e}") from e
    finally:
        await client.close()
    return {"status": "success", "entity_id": action.entity_id, "result": result}
