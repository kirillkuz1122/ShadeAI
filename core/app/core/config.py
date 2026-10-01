from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Shade Core"
    api_key: str = "change-me"

    db_url: str = "sqlite+aiosqlite:///./shade.db"

    ha_base_url: str = "http://127.0.0.1:8123"
    ha_token: str = ""

    llm_model_path: str = "./models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


settings = Settings()
