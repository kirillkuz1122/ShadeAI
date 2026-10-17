from fastapi import Request

from app.services.ha_bridge.client import HAClient


def get_ha_client(request: Request) -> HAClient:
    return request.app.state.ha_client
