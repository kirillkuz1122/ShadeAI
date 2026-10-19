import ipaddress
import re
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, ValidationError, field_validator, model_validator
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
    ha_timeout_seconds: float = Field(default=5, ge=0.1, le=30)
    ha_telemetry_entities: list[str] = Field(default_factory=list, max_length=100)
    sensor_retention_days: int = Field(default=90, ge=1, le=365)
    sensor_history_max_rows: int = Field(default=100_000, ge=1000, le=500_000)
    analytics_presence_entity: str | None = None
    analytics_timezone: str = "Asia/Yekaterinburg"
    analytics_interval_seconds: int = Field(default=3600, ge=60, le=86400)
    automation_allowed_lights: list[str] = Field(default_factory=list, max_length=20)
    automation_execution_enabled: bool = False
    automation_home_presence_entity: str | None = None
    automation_cancel_seconds: int = Field(default=30, ge=10, le=120)
    automation_cooldown_seconds: int = Field(default=1800, ge=300, le=86400)
    suggestions_interval_seconds: int = Field(default=30, ge=5, le=3600)
    calendar_url: str | None = Field(default=None, repr=False)
    calendar_username: str = Field(default="", max_length=128, repr=False)
    calendar_password: str = Field(default="", max_length=512, repr=False)
    calendar_timezone: str = "Asia/Yekaterinburg"
    calendar_interval_seconds: int = Field(default=300, ge=60, le=3600)
    meeting_mode_enabled: bool = False
    meeting_mode_allowed_switches: list[str] = Field(default_factory=list, max_length=5)
    calendar_reminders_enabled: bool = False
    calendar_reminder_lead_minutes: int = Field(default=10, ge=1, le=120)
    calendar_timeout_seconds: int = Field(default=10, ge=1, le=30)
    event_retention_days: int = Field(default=90, ge=1, le=365)
    log_dir: str = "./logs"
    log_max_bytes: int = Field(default=1_048_576, ge=1024, le=10_485_760)
    log_backup_count: int = Field(default=3, ge=1, le=10)

    @field_validator("ha_telemetry_entities")
    @classmethod
    def check_telemetry_entities(cls, value: list[str]) -> list[str]:
        if any(
            len(entity) > 255 or not re.fullmatch(r"(?:sensor|binary_sensor)\.[a-z0-9_]+", entity)
            for entity in value
        ):
            raise ValueError("Ожидался список entity_id датчиков sensor/binary_sensor")
        return list(dict.fromkeys(value))

    @field_validator("analytics_presence_entity", mode="before")
    @classmethod
    def normalize_presence_entity(cls, value):
        return None if value == "" else value

    @model_validator(mode="after")
    def check_analytics_source(self):
        entity = self.analytics_presence_entity
        if entity is not None and (
            not entity.startswith("binary_sensor.") or entity not in self.ha_telemetry_entities
        ):
            raise ValueError("ANALYTICS_PRESENCE_ENTITY должен быть уже выбранным binary_sensor")
        return self

    @field_validator("automation_home_presence_entity", mode="before")
    @classmethod
    def normalize_home_presence(cls, value):
        return None if value == "" else value

    @model_validator(mode="after")
    def check_execution_sources(self):
        home = self.automation_home_presence_entity
        if home is not None and (
            not re.fullmatch(r"binary_sensor\.[a-z0-9_]+", home)
            or home not in self.ha_telemetry_entities
            or home == self.analytics_presence_entity
        ):
            raise ValueError("Общее присутствие должно быть другим выбранным binary_sensor")
        if self.automation_execution_enabled and (
            home is None
            or self.analytics_presence_entity is None
            or not self.automation_allowed_lights
        ):
            raise ValueError("Исполнителю нужны два выбранных источника и явные цели света")
        return self

    @field_validator("automation_allowed_lights")
    @classmethod
    def check_automation_lights(cls, value: list[str]) -> list[str]:
        if any(
            len(entity) > 255 or not re.fullmatch(r"light\.[a-z0-9_]+", entity) for entity in value
        ):
            raise ValueError("AUTOMATION_ALLOWED_LIGHTS должен содержать только entity_id light")
        return list(dict.fromkeys(value))

    @field_validator("calendar_url", mode="before")
    @classmethod
    def check_calendar_url(cls, value):
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError("CALENDAR_URL: ожидается строка")
        try:
            url = urlsplit(value)
            address = ipaddress.ip_address(url.hostname or "")
            local = address.is_loopback or any(
                address in ipaddress.ip_network(net)
                for net in (
                    "10.0.0.0/8",
                    "172.16.0.0/12",
                    "192.168.0.0/16",
                    "fc00::/7",
                    "fe80::/10",
                )
            )
            if (
                not local
                or url.scheme not in {"http", "https"}
                or url.username is not None
                or url.password is not None
                or url.query
                or url.fragment
                or not url.path.endswith("/")
                or "%" in (url.hostname or "")
                or len(value) > 2048
                or any(ord(c) < 33 for c in value)
            ):
                raise ValueError
            if url.port is not None and not 1 <= url.port <= 65535:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError(
                "CALENDAR_URL: нужен локальный IP и URL коллекции без credentials/query"
            ) from None
        return value

    @model_validator(mode="after")
    def check_calendar_credentials(self):
        if bool(self.calendar_username) != bool(self.calendar_password) or any(
            ord(c) < 32 for c in self.calendar_username + self.calendar_password
        ):
            raise ValueError("CalDAV: задайте обе credentials или оставьте обе пустыми")
        return self

    @field_validator("meeting_mode_allowed_switches")
    @classmethod
    def check_meeting_switches(cls, value):
        if any(len(e) > 255 or not re.fullmatch(r"switch\.[a-z0-9_]+", e) for e in value):
            raise ValueError("MEETING_MODE_ALLOWED_SWITCHES: только явные switch.*")
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def check_meeting_enabled(self):
        if self.meeting_mode_enabled and not self.meeting_mode_allowed_switches:
            raise ValueError("Режиму встречи нужен непустой явный список DND-переключателей")
        return self

    @field_validator("ha_token")
    @classmethod
    def check_ha_token(cls, value: str) -> str:
        if value and (
            not value.isascii() or any(ord(char) < 33 or ord(char) > 126 for char in value)
        ):
            raise ValueError("HA_TOKEN: нужен токен без пробелов и управляющих символов")
        return value

    @field_validator("ha_base_url")
    @classmethod
    def check_ha_url(cls, value: str) -> str:
        try:
            url = urlsplit(value)
            valid = (
                url.scheme in {"http", "https"}
                and url.hostname
                and not url.username
                and not url.password
                and not url.query
                and not url.fragment
                and url.path in {"", "/"}
                and url.port != 0
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("HA_BASE_URL: нужен http(s) адрес локального HA без пути и секретов")
        return value.rstrip("/")

    llm_model_path: str = "./models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
    llm_enabled: bool = False
    llm_context_size: int = Field(default=1024, ge=256, le=2048)
    llm_threads: int = Field(default=2, ge=1, le=4)
    llm_max_tokens: int = Field(default=128, ge=1, le=256)
    llm_memory_limit_mb: int = Field(default=2304, ge=512, le=2560)
    llm_load_timeout_seconds: float = Field(default=120, ge=1, le=300)
    llm_inference_timeout_seconds: float = Field(default=30, ge=0.1, le=300)

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    notification_retention_days: int = Field(default=30, ge=1, le=365)
    notification_processor: Literal["disabled", "diagnostic", "llm"] = "disabled"
    notification_timezone: str = "Asia/Yekaterinburg"
    notification_queue_size: int = Field(default=64, ge=1, le=256)
    notification_processing_timeout_seconds: float = Field(default=30, ge=0.1, le=300)
    notification_shutdown_seconds: float = Field(default=5, ge=0.1, le=30)
    notification_allowed_apps: list[str] = Field(
        default=[
            "ru.ozon.app.android",
            "com.wildberries.ru",
            "ru.yandex.taxi",
        ],
        max_length=100,
    )

    @field_validator("notification_timezone", "analytics_timezone", "calendar_timezone")
    @classmethod
    def check_notification_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Нужен часовой пояс IANA") from None
        return value

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
            "NOTIFICATION_ALLOWED_APPS и HA_TELEMETRY_ENTITIES задаются JSON-массивами"
        )
    raise RuntimeError(
        f"Ошибка настройки Shade Core: {detail}. "
        "Выполните python -m app.setup из core/ и проверьте .env."
    ) from None


settings = load_settings()
