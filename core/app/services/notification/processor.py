from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas import NotificationIn
from app.services.notification.extraction import ExtractedNotification


class ProcessingResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    processor: Literal["diagnostic"]
    llm: Literal[False] = False


Result = ProcessingResult | ExtractedNotification


def validate_result(raw) -> Result:
    payload = (
        raw.model_dump(warnings=False)
        if isinstance(raw, (ProcessingResult, ExtractedNotification))
        else raw
    )
    if isinstance(payload, dict) and payload.get("processor") == "llm":
        return ExtractedNotification.model_validate(payload)
    return ProcessingResult.model_validate(payload)


async def process_notification(notification: NotificationIn) -> ProcessingResult:
    """Проверка конвейера без классификации, извлечения текста и команд HA."""
    return ProcessingResult(processor="diagnostic")
