import time
from pathlib import Path

import httpx
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["system"])

_started_at = time.monotonic()


@router.get("/health")
async def health() -> dict:
    ha_connected = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(
                f"{settings.ha_base_url}/api/",
                headers={"Authorization": f"Bearer {settings.ha_token}"},
            )
            ha_connected = resp.status_code == 200
    except httpx.HTTPError:
        pass

    db_path = settings.db_url.split("///")[-1]
    db_size = Path(db_path).stat().st_size / 1024 / 1024 if Path(db_path).exists() else 0.0

    return {
        "status": "ok",
        "uptime": int(time.monotonic() - _started_at),
        "ha_connected": ha_connected,
        "llm_status": "not_loaded",
        "db_size": f"{db_size:.1f} MB",
    }
