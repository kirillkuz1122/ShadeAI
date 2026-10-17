import math
from typing import Annotated, Any, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

Name = Annotated[str, Field(strict=True, min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]
EntityId = Annotated[
    str, Field(strict=True, max_length=255, pattern=r"^[a-z][a-z0-9_]*\.[a-z0-9_]+$")
]


def validate_params(value: dict) -> dict:
    if {"entity_id", "device_id", "area_id", "target"} & value.keys():
        raise ValueError("Цель команды задаётся только entity_id маршрута")
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > 8 or count > 512:
            raise ValueError("Слишком сложные параметры команды")
        if isinstance(item, dict):
            if len(item) > 64 or any(len(key) > 64 for key in item):
                raise ValueError("Слишком много параметров или длинное имя")
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            if len(item) > 64:
                raise ValueError("Слишком длинный список параметров")
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, str) and len(item) > 8192:
            raise ValueError("Слишком длинный параметр")
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError("Неконечное число в параметрах")
    return value


class HACommand(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    action: Name
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("params")
    @classmethod
    def check_params(cls, value: dict) -> dict:
        return validate_params(value)


class HAAction(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    domain: Name
    service: Name
    entity_id: EntityId
    data: dict[str, Any] | None = None

    @field_validator("data")
    @classmethod
    def check_data(cls, value: dict | None) -> dict | None:
        return validate_params(value) if value is not None else None

    @model_validator(mode="after")
    def match_domain(self) -> Self:
        if self.entity_id.split(".")[0] != self.domain:
            raise ValueError("Домен и entity_id должны совпадать")
        return self


class HAState(BaseModel):
    entity_id: EntityId
    state: Annotated[str, Field(strict=True, max_length=255)]
    attributes: dict[str, Any]
    last_changed: AwareDatetime
    last_updated: AwareDatetime

    @field_validator("last_changed", "last_updated", mode="before")
    @classmethod
    def string_timestamp(cls, value):
        if not isinstance(value, str):
            raise ValueError("Ожидалось время ISO 8601")
        return value
