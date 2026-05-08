from typing import Dict
from app.adapters.base import BaseAgentAdapter


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: Dict[str, BaseAgentAdapter] = {}

    def register(self, session_id: str, adapter: BaseAgentAdapter) -> None:
        self._adapters[session_id] = adapter

    def get(self, session_id: str) -> BaseAgentAdapter:
        adapter = self._adapters.get(session_id)
        if adapter is None:
            raise KeyError(f"No adapter for session '{session_id}'")
        return adapter

    async def remove(self, session_id: str) -> None:
        adapter = self._adapters.pop(session_id, None)
        if adapter is not None:
            await adapter.stop()


_registry = AdapterRegistry()


def get_registry() -> AdapterRegistry:
    return _registry
