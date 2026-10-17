import re
from datetime import datetime, timedelta
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core import clock

Priority = Literal["min", "low", "default", "high", "max"]


class NotificationIn(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    app_name: Annotated[
        str,
        Field(
            strict=True,
            min_length=3,
            max_length=255,
            pattern=r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z0-9_]+)+$",
        ),
    ]
    title: Annotated[str, Field(strict=True, max_length=512)]
    text: Annotated[str, Field(strict=True, max_length=8192)]
    timestamp: Annotated[str, Field(strict=True, min_length=20, max_length=40)]
    priority: Priority = "default"
    event_id: UUID | None = None

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        if not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?"
            r"(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)",
            value,
        ):
            raise ValueError("Нужна дата ISO 8601 с часовым поясом")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            normalized = clock.iso_utc(parsed)
        except (ValueError, OverflowError):
            raise ValueError("Неверная дата ISO 8601") from None
        if parsed > clock.utcnow() + timedelta(minutes=5):
            raise ValueError("Время уведомления более чем на 5 минут в будущем")
        return normalized

    @model_validator(mode="after")
    def require_content(self) -> Self:
        if not self.title.strip() and not self.text.strip():
            raise ValueError("Заголовок и текст не могут быть пустыми одновременно")
        return self


class NotificationReceipt(BaseModel):
    id: int | None
    status: Literal["stored", "duplicate", "skipped"]
    reason: Literal["privacy_policy", "expired"] | None = None
    processed_data: None = None


class NotificationOut(BaseModel):
    id: int
    app_name: str
    title: str
    text: str
    timestamp: str
    priority: str
    event_id: str | None
    status: Literal["stored", "processed"]
    category: str | None
    processed_data: dict | None
    created_at: str


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    total: int
