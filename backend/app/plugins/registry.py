from typing import Dict
from app.db.interface import IAgentDatabase
from app.plugins.runner import PluginRunner


class PluginRunnerRegistry:
    """In-memory map of plugin_id -> PluginRunner. Singleton."""

    def __init__(self) -> None:
        self._runners: Dict[str, PluginRunner] = {}

    def get_or_create(self, plugin_id: str, db: IAgentDatabase) -> PluginRunner:
        runner = self._runners.get(plugin_id)
        if runner is None:
            runner = PluginRunner(plugin_id, db)
            self._runners[plugin_id] = runner
        return runner

    def get(self, plugin_id: str) -> PluginRunner | None:
        return self._runners.get(plugin_id)

    async def remove(self, plugin_id: str) -> None:
        runner = self._runners.pop(plugin_id, None)
        if runner is not None:
            await runner.stop()


_registry = PluginRunnerRegistry()


def get_plugin_registry() -> PluginRunnerRegistry:
    return _registry
