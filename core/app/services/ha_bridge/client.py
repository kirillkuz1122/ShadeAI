import asyncio
import json
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from app.core.config import settings
from app.services.ha_bridge.models import HAState

MAX_HA_RESPONSE_BYTES = 2 * 1024 * 1024


class HAError(Exception):
    def __init__(self, code: str, status_code: int = 503, outcome: str = "unknown"):
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.outcome = outcome


def reject_constant(value):
    raise ValueError("Неверный JSON")


class HAClient:
    def __init__(self) -> None:
        self.configured = bool(settings.ha_token)
        self.timeout = settings.ha_timeout_seconds
        self._client = httpx.AsyncClient(
            base_url=settings.ha_base_url,
            headers={"Authorization": f"Bearer {settings.ha_token}"},
            timeout=self.timeout,
            trust_env=False,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=2),
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload=None,
        state_lookup=False,
        timeout: float | None = None,
    ) -> Any:
        if not self.configured:
            raise HAError("HA_NOT_CONFIGURED", outcome="not_sent")
        budget = min(timeout, self.timeout) if timeout else self.timeout
        try:
            async with asyncio.timeout(budget):
                async with self._client.stream(
                    method, path, json=payload, timeout=budget
                ) as response:
                    status = response.status_code
                    if status in {401, 403}:
                        raise HAError("HA_AUTH_FAILED", outcome="rejected")
                    if status == 404 and state_lookup:
                        raise HAError("ENTITY_NOT_FOUND", 404, "rejected")
                    if status in {400, 404, 422} and method == "POST":
                        raise HAError("HA_COMMAND_REJECTED", 400, "rejected")
                    if status >= 500:
                        raise HAError("HA_SERVER_ERROR", 502)
                    if status != 200:
                        raise HAError("HA_BAD_RESPONSE", 502)
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > MAX_HA_RESPONSE_BYTES:
                            raise HAError("HA_BAD_RESPONSE", 502)
                        body.extend(chunk)
                    return json.loads(body, parse_constant=reject_constant)
        except HAError:
            raise
        except (httpx.ConnectTimeout, httpx.PoolTimeout):
            raise HAError("HA_TIMEOUT", 504, "not_sent") from None
        except (TimeoutError, httpx.TimeoutException):
            raise HAError("HA_TIMEOUT", 504) from None
        except httpx.ConnectError:
            raise HAError("HA_UNAVAILABLE", outcome="not_sent") from None
        except httpx.HTTPError:
            raise HAError("HA_UNAVAILABLE") from None
        except (ValueError, RecursionError):
            raise HAError("HA_BAD_RESPONSE", 502) from None

    async def ping(self) -> None:
        body = await self._request("GET", "/api/", timeout=2)
        if not isinstance(body, dict) or body.get("message") != "API running.":
            raise HAError("HA_BAD_RESPONSE", 502)

    async def get_states(self) -> list[HAState]:
        body = await self._request("GET", "/api/states")
        if not isinstance(body, list) or len(body) > 5000:
            raise HAError("HA_BAD_RESPONSE", 502)
        try:
            return TypeAdapter(list[HAState]).validate_python(body)
        except ValidationError:
            raise HAError("HA_BAD_RESPONSE", 502) from None

    async def get_state(self, entity_id: str) -> HAState:
        body = await self._request("GET", f"/api/states/{entity_id}", state_lookup=True)
        try:
            state = HAState.model_validate(body)
            if state.entity_id != entity_id:
                raise HAError("HA_BAD_RESPONSE", 502)
            return state
        except ValidationError:
            raise HAError("HA_BAD_RESPONSE", 502) from None

    async def call_service(
        self, domain: str, service: str, entity_id: str, data: dict | None = None
    ) -> list:
        body = await self._request(
            "POST",
            f"/api/services/{domain}/{service}",
            payload={**(data or {}), "entity_id": entity_id},
        )
        if not isinstance(body, list) or len(body) > 5000:
            raise HAError("HA_BAD_RESPONSE", 502)
        try:
            TypeAdapter(list[HAState]).validate_python(body)
        except ValidationError:
            raise HAError("HA_BAD_RESPONSE", 502) from None
        return body

    async def close(self) -> None:
        await self._client.aclose()
