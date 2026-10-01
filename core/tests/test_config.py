import pytest
from pydantic import ValidationError

from app.core.config import Settings, load_settings

TEST_KEY = "shade-config-test-key-000000000001"


def test_settings_read_canonical_key_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("SHADE_API_KEY", raising=False)
    path = tmp_path / ".env"
    path.write_text(f"SHADE_API_KEY={TEST_KEY}\n", encoding="utf-8")
    assert Settings(_env_file=path).api_key == TEST_KEY


def test_environment_key_overrides_env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(f"SHADE_API_KEY={TEST_KEY}\n", encoding="utf-8")
    override = "shade-environment-test-key-000001"
    monkeypatch.setenv("SHADE_API_KEY", override)
    assert Settings(_env_file=path).api_key == override


def test_legacy_key_does_not_replace_canonical_key(monkeypatch):
    monkeypatch.delenv("SHADE_API_KEY", raising=False)
    monkeypatch.setenv("API_KEY", TEST_KEY)
    with pytest.raises(ValidationError, match="SHADE_API_KEY"):
        Settings(_env_file=None)


@pytest.mark.parametrize("key", ["", "change-me", "change-me-to-long-random-string", "a" * 31])
def test_settings_reject_missing_or_placeholder_key(key, monkeypatch):
    monkeypatch.setenv("SHADE_API_KEY", key)
    with pytest.raises(ValidationError, match="не менее 32"):
        Settings(_env_file=None)


def test_invalid_key_is_not_in_error_or_settings_repr(monkeypatch):
    invalid = TEST_KEY + " secret"
    monkeypatch.setenv("SHADE_API_KEY", invalid)
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None)
    assert invalid not in str(caught.value)
    monkeypatch.setenv("SHADE_API_KEY", TEST_KEY)
    assert TEST_KEY not in repr(Settings(_env_file=None))


def test_startup_error_explains_setup_without_leaking_secret(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SHADE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="python -m app.setup") as caught:
        load_settings()
    assert "обязательный ключ не задан" in str(caught.value)
