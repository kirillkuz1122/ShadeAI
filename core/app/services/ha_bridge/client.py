import httpx

from app.core.config import settings


class HAClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.ha_base_url,
            headers={"Authorization": f"Bearer {settings.ha_token}"},
            timeout=10.0,
        )

    async def get_states(self) -> list[dict]:
        resp = await self._client.get("/api/states")
        resp.raise_for_status()
        return resp.json()

    async def get_state(self, entity_id: str) -> dict:
        resp = await self._client.get(f"/api/states/{entity_id}")
        resp.raise_for_status()
        return resp.json()

    async def call_service(
        self, domain: str, service: str, entity_id: str, data: dict | None = None
    ) -> list:
        payload = {"entity_id": entity_id, **(data or {})}
        resp = await self._client.post(f"/api/services/{domain}/{service}", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._client.aclose()
