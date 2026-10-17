import re

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, SettingsError

from app.core.credentials import validate_api_key


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = "Shade Core"
    api_key: str = Field(validation_alias="SHADE_API_KEY", repr=False)

    db_url: str = "sqlite+aiosqlite:///./shade.db"

    ha_base_url: str = "http://127.0.0.1:8123"
    ha_token: str = Field(default="", repr=False)

    llm_model_path: str = "./models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    notification_retention_days: int = Field(default=30, ge=1, le=365)
    notification_allowed_apps: list[str] = Field(
        default=[
            "ru.ozon.app.android",
            "com.wildberries.ru",
            "ru.yandex.taxi",
        ],
        max_length=100,
    )

    @field_validator("notification_allowed_apps")
    @classmethod
    def check_notification_apps(cls, value: list[str]) -> list[str]:
        if any(
            len(name) > 255 or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z0-9_]+)+", name)
            for name in value
        ):
            raise ValueError("Нужны имена пакетов приложений, не длиннее 255 символов")
        return value

    @field_validator("api_key")
    @classmethod
    def check_api_key(cls, value: str) -> str:
        return validate_api_key(value)


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        messages = []
        for error in exc.errors(include_input=False):
            field = ".".join(str(part) for part in error["loc"])
            message = "обязательный ключ не задан" if error["type"] == "missing" else error["msg"]
            messages.append(f"{field}: {message}")
        detail = "; ".join(messages)
    except SettingsError:
        detail = (
            "неверный формат переменных окружения; CORS_ORIGINS и "
            "NOTIFICATION_ALLOWED_APPS задаются JSON-массивами"
        )
    raise RuntimeError(
        f"Ошибка настройки Shade Core: {detail}. "
        "Выполните python -m app.setup из core/ и проверьте .env."
    ) from None


settings = load_settings()
