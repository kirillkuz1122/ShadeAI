import asyncio
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any

Handler = Callable[[dict[str, Any]], Coroutine]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: defaultdict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._subscribers[event_type].append(handler)

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        for handler in self._subscribers.get(event_type, []):
            asyncio.create_task(handler(payload))


bus = EventBus()
