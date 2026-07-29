import logging
from typing import Any

from app.adapters.registry import AdapterRegistry
from app.db.interface import IAgentDatabase
from app.models.domain import MessageRole


logger = logging.getLogger("agentzoo.plugin_actions")


class PluginActionDispatcher:
    """Executes whitelisted actions requested by plugin processes."""

    def __init__(self, db: IAgentDatabase, session_registry: AdapterRegistry) -> None:
        self._db = db
        self._session_registry = session_registry

    async def dispatch(
        self,
        *,
        plugin_instance_id: str,
        plugin_run_id: str,
        action: str,
        data: dict[str, Any],
    ) -> None:
        if action == "session.message.send":
            await self._send_session_message(plugin_instance_id, data)
            return
        raise RuntimeError(f"unsupported plugin action: {action}")

    async def _send_session_message(self, plugin_instance_id: str, data: dict[str, Any]) -> None:
        session_id = data.get("session_id")
        content = data.get("content")
        if not isinstance(session_id, str) or not session_id:
            raise RuntimeError("session.message.send requires data.session_id")
        if not isinstance(content, str) or not content:
            raise RuntimeError("session.message.send requires data.content")

        await self._db.get_session(session_id)
        source = f"plugin:{plugin_instance_id}"
        try:
            runner = self._session_registry.get(session_id)
        except KeyError:
            logger.warning("plugin action target session has no live runner: %s", session_id)
            await self._db.add_message(
                session_id,
                MessageRole.USER,
                content,
                from_session_id=source,
            )
            return
        await runner.submit(content, from_session_id=source)
