import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


logger = logging.getLogger("agentzoo.plugin_events")


class PluginEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "agentzoo"
    data: dict[str, Any]


class PluginEventBus:
    """Small in-process event bus for plugin hooks.

    Subscribers are async callables. Publishing is best-effort: one broken
    subscriber is logged but does not prevent other deliveries.
    """

    def __init__(self) -> None:
        self._subscribers: list[Any] = []

    def subscribe(self, handler: Any) -> None:
        if handler not in self._subscribers:
            self._subscribers.append(handler)

    async def publish(self, event: PluginEvent) -> None:
        for handler in list(self._subscribers):
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("plugin event subscriber failed event=%s", event.type)


_event_bus = PluginEventBus()


def get_plugin_event_bus() -> PluginEventBus:
    return _event_bus
