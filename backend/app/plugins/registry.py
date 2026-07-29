from typing import Dict

from app.db.interface import IAgentDatabase
from app.plugins.actions import PluginActionDispatcher
from app.plugins.runner import PluginRunner


class PluginRunnerRegistry:
    """In-memory map of plugin instance id -> PluginRunner."""

    def __init__(self) -> None:
        self._runners: Dict[str, PluginRunner] = {}

    def get_or_create(
        self,
        instance_id: str,
        db: IAgentDatabase,
        action_dispatcher: PluginActionDispatcher | None = None,
    ) -> PluginRunner:
        runner = self._runners.get(instance_id)
        if runner is None:
            runner = PluginRunner(instance_id, db, action_dispatcher)
            self._runners[instance_id] = runner
        else:
            runner.set_action_dispatcher(action_dispatcher)
        return runner

    def get(self, instance_id: str) -> PluginRunner | None:
        return self._runners.get(instance_id)

    async def remove(self, instance_id: str) -> None:
        runner = self._runners.pop(instance_id, None)
        if runner is not None:
            await runner.stop()


_registry = PluginRunnerRegistry()


def get_plugin_registry() -> PluginRunnerRegistry:
    return _registry
