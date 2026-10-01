"""LLM Engine — точка интеграции llama-cpp-python.

Реализация появится в MVP v0.3. Сейчас здесь только интерфейс,
чтобы остальной код мог зависеть от него, не зная деталей инференса.
"""

from abc import ABC, abstractmethod


class LLMEngine(ABC):
    @abstractmethod
    async def extract_entities(self, text: str) -> dict:
        """Извлечь категорию, сущности и интент из текста уведомления."""


class StubLLMEngine(LLMEngine):
    async def extract_entities(self, text: str) -> dict:
        return {"category": "noise", "is_actionable": False, "entities": {}, "confidence": 0.0}


engine: LLMEngine = StubLLMEngine()
