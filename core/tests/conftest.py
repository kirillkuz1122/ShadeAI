import os
import socket
import tempfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_KEY = "shade-test-key-for-local-checks-0001"
TEST_HA_TOKEN = "shade-test-ha-token"
TEST_ENV = {
    "APP_NAME": "Shade Core tests",
    "SHADE_API_KEY": TEST_KEY,
    "DB_URL": "sqlite+aiosqlite:///./bootstrap.db",
    "HA_BASE_URL": "http://ha.test:8123",
    "HA_TOKEN": TEST_HA_TOKEN,
    "HA_TIMEOUT_SECONDS": "5",
    "HA_TELEMETRY_ENTITIES": "[]",
    "SENSOR_RETENTION_DAYS": "90",
    "SENSOR_HISTORY_MAX_ROWS": "100000",
    "EVENT_RETENTION_DAYS": "90",
    "LOG_DIR": "./logs",
    "LOG_MAX_BYTES": "1048576",
    "LOG_BACKUP_COUNT": "3",
    "LLM_MODEL_PATH": "./missing-test-model.gguf",
    "CORS_ORIGINS": '["http://testserver"]',
    "NOTIFICATION_RETENTION_DAYS": "30",
    "NOTIFICATION_ALLOWED_APPS": '["ru.ozon.app.android","com.wildberries.ru","ru.yandex.taxi"]',
}


def set_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    names = {name.lower() for name in TEST_ENV} | {"api_key"}
    for name in list(os.environ):
        if name.lower() in names:
            monkeypatch.delenv(name)
    for name, value in TEST_ENV.items():
        monkeypatch.setenv(name, value)


def pytest_configure(config: pytest.Config) -> None:
    # Settings и engine создаются при импорте: изоляция нужна до сбора тестов.
    cache = Path(__file__).resolve().parents[1] / ".pytest_cache"
    cache.mkdir(exist_ok=True)
    if config.option.basetemp is not None:
        config.option.basetemp = str(Path(config.option.basetemp).resolve())
    workspace = tempfile.TemporaryDirectory(prefix="shade-tests-", dir=cache)
    monkeypatch = pytest.MonkeyPatch()

    def cleanup():
        monkeypatch.undo()
        workspace.cleanup()

    config.add_cleanup(cleanup)
    monkeypatch.chdir(workspace.name)
    set_test_environment(monkeypatch)
    if config.option.basetemp is None:
        config.option.basetemp = str(Path(workspace.name) / "tmp")


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    set_test_environment(monkeypatch)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    attempts = []
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def block_network():
        attempts.append(True)
        raise AssertionError("Сеть в тестах запрещена: используйте mock-транспорт")

    def connect(sock, address):
        if sock.family in {socket.AF_INET, socket.AF_INET6}:
            block_network()
        return original_connect(sock, address)

    def connect_ex(sock, address):
        if sock.family in {socket.AF_INET, socket.AF_INET6}:
            block_network()
        return original_connect_ex(sock, address)

    def getaddrinfo(*args, **kwargs):
        block_network()

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield
    # Даже если роутер поймал исключение, попытка реального запроса — ошибка теста.
    assert not attempts, "Тест попытался обратиться к реальной сети"


class HAMock:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.available = True
        self.status_code = 200
        self.state = {
            "entity_id": "light.test",
            "state": "on",
            "attributes": {
                "friendly_name": "Тестовый свет",
                "brightness": 128,
            },
            "last_changed": "2026-10-17T10:00:00Z",
            "last_updated": "2026-10-17T10:00:01Z",
        }
        self.states = [self.state]
        self.result = [self.state]
        self.clients = []
        self.error = None
        self.overrides = {}
        self.hook = None
        self.unexpected_requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        known_route = (
            request.method == "GET"
            and request.url.path
            in {
                "/api/",
                "/api/states",
                "/api/states/light.test",
            }
        ) or (request.method == "POST" and request.url.path == "/api/services/light/turn_on")
        if (
            request.url.host != "ha.test"
            or request.headers.get("Authorization") != f"Bearer {TEST_HA_TOKEN}"
            or not known_route
        ):
            self.unexpected_requests.append(request)
            raise AssertionError("Неожиданный запрос к mock Home Assistant")
        if not self.available:
            raise httpx.ConnectError("Тестовый HA недоступен", request=request)
        if self.error:
            raise self.error
        if self.hook:
            self.hook(request)
        if request.url.path in self.overrides:
            return self.overrides[request.url.path]()
        if request.url.path == "/api/":
            body = {"message": "API running."}
        elif request.url.path == "/api/states":
            body = self.states
        elif request.url.path == "/api/states/light.test":
            body = self.state
        else:
            body = self.result
        return httpx.Response(self.status_code, json=body)


@pytest.fixture
def ha_mock(monkeypatch):
    mock = HAMock()
    transport = httpx.MockTransport(mock.handle)
    original_client = httpx.AsyncClient

    def async_client(*args, **kwargs):
        kwargs["transport"] = transport
        kwargs["trust_env"] = False
        client = original_client(*args, **kwargs)
        mock.clients.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", async_client)
    yield mock
    assert not mock.unexpected_requests, "Обнаружен неожиданный запрос к mock HA"


@pytest.fixture
def client(tmp_path, monkeypatch, ha_mock):
    from app.core.config import settings
    from app.db import base
    from app.main import create_app

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'shade.db'}"
    monkeypatch.setattr(settings, "db_url", db_url)
    engine = base.create_db_engine(db_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(base, "engine", engine)
    monkeypatch.setattr(base, "async_session", session_factory)
    with TestClient(create_app()) as test_client:
        yield test_client
    assert test_client.app.state.ha_client._client.is_closed


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {TEST_KEY}"}
