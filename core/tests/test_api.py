import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "ha_connected" in data


def test_ingest_requires_auth(client):
    resp = client.post("/api/v1/notifications", json={})
    assert resp.status_code == 401


def test_ingest_and_list(client):
    headers = {"Authorization": f"Bearer {settings.api_key}"}
    payload = {
        "app_name": "ru.ozon.app.android",
        "title": "Ozon Доставка",
        "text": "Курьер прибудет сегодня с 18:00 до 20:00",
        "timestamp": "2026-09-17T11:00:00Z",
        "priority": "high",
    }
    resp = client.post("/api/v1/notifications", json=payload, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["status"] == "queued"

    resp = client.get("/api/v1/notifications", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


def test_ha_action_unreachable(client):
    headers = {"Authorization": f"Bearer {settings.api_key}"}
    resp = client.post(
        "/api/v1/ha/action",
        json={"domain": "light", "service": "turn_on", "entity_id": "light.test"},
        headers=headers,
    )
    assert resp.status_code == 503
