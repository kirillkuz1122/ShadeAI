import stat

import pytest
from dotenv import dotenv_values

from app.setup import initialize_env, main


def test_setup_creates_private_env_with_random_key(tmp_path):
    path = tmp_path / ".env"
    assert initialize_env(path)
    values = dotenv_values(path)
    assert len(values["SHADE_API_KEY"]) >= 32
    assert values["DB_URL"] == "sqlite+aiosqlite:///./shade.db"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    other = tmp_path / "other.env"
    initialize_env(other)
    assert dotenv_values(other)["SHADE_API_KEY"] != values["SHADE_API_KEY"]


def test_setup_preserves_existing_key_and_other_settings(tmp_path):
    path = tmp_path / ".env"
    content = "SHADE_API_KEY=shade-existing-key-00000000000001\nHA_TOKEN=local-test-token\n"
    path.write_text(content, encoding="utf-8")
    path.chmod(0o644)
    assert not initialize_env(path)
    assert path.read_text(encoding="utf-8") == content
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("value", ["", "change-me", "change-me-to-long-random-string"])
def test_setup_replaces_placeholder_without_resetting_ha(tmp_path, value):
    path = tmp_path / ".env"
    path.write_text(f"SHADE_API_KEY={value}\nHA_TOKEN=local-test-token\n", encoding="utf-8")
    assert initialize_env(path)
    values = dotenv_values(path)
    assert len(values["SHADE_API_KEY"]) >= 32
    assert values["HA_TOKEN"] == "local-test-token"


def test_setup_does_not_overwrite_invalid_custom_key(tmp_path):
    path = tmp_path / ".env"
    content = "SHADE_API_KEY=custom-short-key\n"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="не менее 32"):
        initialize_env(path)
    assert path.read_text(encoding="utf-8") == content


def test_setup_rejects_symlink(tmp_path):
    original = tmp_path / "original.env"
    original.write_text("HA_TOKEN=local-test-token\n", encoding="utf-8")
    link = tmp_path / ".env"
    link.symlink_to(original)
    with pytest.raises(ValueError, match="символической ссылкой"):
        initialize_env(link)
    assert original.read_text(encoding="utf-8") == "HA_TOKEN=local-test-token\n"


def test_setup_cli_does_not_print_generated_key(tmp_path, monkeypatch, capsys):
    path = tmp_path / ".env"
    monkeypatch.setattr("sys.argv", ["app.setup", "--env-file", str(path)])
    main()
    output = capsys.readouterr()
    assert "Ключ создан" in output.out
    assert dotenv_values(path)["SHADE_API_KEY"] not in output.out + output.err
