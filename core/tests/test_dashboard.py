from pathlib import Path

import pytest

from app.core.config import settings
from app.core.web import LocalDashboard


@pytest.fixture
def dashboard(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "assets").mkdir()
    (dist / "index.html").write_text('<html><script src="/assets/app-12345678.js"></script></html>')
    (dist / "assets/app-12345678.js").write_text("console.log('local')")
    (dist / "shade.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    monkeypatch.setattr(settings, "web_dist_path", str(dist))
    return dist


def test_local_dashboard_and_api(dashboard, client, auth_headers):
    response = client.get("/")
    assert response.status_code == 200 and "<html>" in response.text
    assert response.headers["cache-control"] == "no-cache"
    assert "connect-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    asset = client.get("/assets/app-12345678.js")
    assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
    assert client.get("/shade.svg").status_code == 200
    assert client.get("/api/v1/notifications").status_code == 401
    assert client.get("/api/v1/notifications", headers=auth_headers).status_code == 200
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/openapi.json").status_code == 200
    for path in (
        "/docs",
        "/redoc",
        "/api/v1/missing",
        "/assets/",
        "/.env",
        "/src/main.tsx",
        "/assets/%2e%2e/.env",
        "/assets/app-12345678.js/extra",
    ):
        assert client.get(path).status_code == 404, path
    assert client.post("/").status_code == 405


def test_dashboard_snapshot_and_symlink_replacement(dashboard, client, tmp_path):
    added = dashboard / "assets/new-12345678.js"
    added.write_text("not in startup manifest")
    assert client.get("/assets/new-12345678.js").status_code == 404
    asset = dashboard / "assets/app-12345678.js"
    asset.unlink()
    secret = tmp_path / "secret"
    secret.write_text("private")
    asset.symlink_to(secret)
    assert client.get("/assets/app-12345678.js").status_code == 404


@pytest.mark.parametrize("name", [".env", "shade.db", "assets/main.tsx", "assets/app.js.map"])
def test_dashboard_rejects_source_or_private_files(dashboard, name):
    (dashboard / name).write_text("not public")
    with pytest.raises(ValueError, match="WEB_DIST_PATH"):
        LocalDashboard(str(dashboard))


def test_dashboard_symlink_and_bounds(dashboard, tmp_path):
    (dashboard / "index.html").unlink()
    with pytest.raises(ValueError):
        LocalDashboard(str(dashboard))
    (dashboard / "index.html").symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError):
        LocalDashboard(str(dashboard))
    (dashboard / "index.html").unlink()
    with (dashboard / "index.html").open("wb") as file:
        file.truncate(33 * 1024**2)
    with pytest.raises(ValueError):
        LocalDashboard(str(dashboard))
    (dashboard / "index.html").write_text("local")
    for number in range(512):
        (dashboard / f"assets/extra-{number}.js").touch()
    with pytest.raises(ValueError):
        LocalDashboard(str(dashboard))


def test_default_mode_has_no_web(client):
    assert settings.web_dist_path is None
    assert client.get("/").status_code == 404


def test_dashboard_rejects_symlink_root(dashboard, tmp_path):
    link = tmp_path / "link"
    link.symlink_to(dashboard, target_is_directory=True)
    with pytest.raises(ValueError):
        LocalDashboard(str(link))
    assert isinstance(dashboard, Path)
