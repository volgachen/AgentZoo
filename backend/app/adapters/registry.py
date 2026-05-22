from typing import Dict
from app.core.runner import SessionRunner


class AdapterRegistry:
    def __init__(self) -> None:
        self._runners: Dict[str, SessionRunner] = {}

    def register(self, session_id: str, runner: SessionRunner) -> None:
        self._runners[session_id] = runner

    def get(self, session_id: str) -> SessionRunner:
        runner = self._runners.get(session_id)
        if runner is None:
            raise KeyError(f"No runner for session '{session_id}'")
        return runner

    async def remove(self, session_id: str) -> None:
        runner = self._runners.pop(session_id, None)
        if runner is not None:
            await runner.stop()


_registry = AdapterRegistry()


def get_registry() -> AdapterRegistry:
    return _registry
