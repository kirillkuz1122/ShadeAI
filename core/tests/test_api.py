import json

import pytest


def test_health(client, ha_mock):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["ha_connected"] is True
    assert data["llm_status"] == "not_loaded"
    assert len(ha_mock.requests) == 1


@pytest.mark.parametrize("failure", ["connection", "http"])
def test_health_with_unavailable_ha(client, ha_mock, failure):
    if failure == "connection":
        ha_mock.available = False
    else:
        ha_mock.status_code = 503
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["ha_connected"] is False


def test_ingest_requires_auth(client):
    resp = client.post("/api/v1/notifications", json={})
    assert resp.status_code == 401


def test_ingest_rejects_wrong_key(client):
    resp = client.post(
        "/api/v1/notifications",
        json={},
        headers={"Authorization": "Bearer wrong-test-key-000000000000000001"},
    )
    assert resp.status_code == 401


def test_ingest_and_list(client, auth_headers):
    initial = client.get("/api/v1/notifications", headers=auth_headers)
    assert initial.json() == {"items": [], "total": 0}
    payload = {
        "app_name": "ru.ozon.app.android",
        "title": "Ozon Доставка",
        "text": "Курьер прибудет сегодня с 18:00 до 20:00",
        "timestamp": "2026-09-17T11:00:00Z",
        "priority": "high",
    }
    resp = client.post("/api/v1/notifications", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["status"] == "queued"
    assert resp.json()["id"] == 1

    resp = client.get("/api/v1/notifications", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["text"] == payload["text"]


@pytest.mark.parametrize("failure", ["connection", "unauthorized", "server_error"])
def test_ha_action_unreachable(client, auth_headers, ha_mock, failure):
    if failure == "connection":
        ha_mock.available = False
    else:
        ha_mock.status_code = 401 if failure == "unauthorized" else 500
    resp = client.post(
        "/api/v1/ha/action",
        json={"domain": "light", "service": "turn_on", "entity_id": "light.test"},
        headers=auth_headers,
    )
    assert resp.status_code == 503
    assert len(ha_mock.requests) == 1


def test_ha_action_success(client, auth_headers, ha_mock):
    payload = {
        "domain": "light",
        "service": "turn_on",
        "entity_id": "light.test",
        "data": {"brightness": 128},
    }
    resp = client.post("/api/v1/ha/action", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "success",
        "entity_id": "light.test",
        "result": ha_mock.result,
    }
    assert len(ha_mock.requests) == 1
    assert json.loads(ha_mock.requests[0].content) == {"entity_id": "light.test", "brightness": 128}


def test_notifications_start_empty_in_another_test(client, auth_headers):
    resp = client.get("/api/v1/notifications", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0}


def test_ha_action_requires_auth(client, ha_mock):
    resp = client.post(
        "/api/v1/ha/action",
        json={"domain": "light", "service": "turn_on", "entity_id": "light.test"},
    )
    assert resp.status_code == 401
    assert ha_mock.requests == []
