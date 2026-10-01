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
            message = (
                "обязательный ключ не задан" if error["type"] == "missing" else error["msg"]
            )
            messages.append(f"{field}: {message}")
        detail = "; ".join(messages)
    except SettingsError:
        detail = "неверный формат переменных окружения; CORS_ORIGINS задаётся JSON-массивом"
    raise RuntimeError(
        f"Ошибка настройки Shade Core: {detail}. "
        "Выполните python -m app.setup из core/ и проверьте .env."
    ) from None


settings = load_settings()
