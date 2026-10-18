from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas import NotificationIn


class ProcessingResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    processor: Literal["diagnostic"]
    llm: Literal[False] = False


async def process_notification(notification: NotificationIn) -> ProcessingResult:
    """Проверка конвейера без классификации, извлечения текста и команд HA."""
    return ProcessingResult(processor="diagnostic")
