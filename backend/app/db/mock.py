from datetime import datetime, timezone
from typing import Dict, List
from app.db.interface import IAgentDatabase
from app.models.domain import (
    AgentTemplate, AgentType, Session, SessionStatus,
    Message, MessageRole,
    Plugin, PluginStatus,
)


_SEED_AGENTS = [
    AgentTemplate(
        id="agent-research-001",
        name="Research Agent",
        description="通过 Arxiv / Web 搜索工具检索论文，汇总后生成研究报告。",
        agent_type=AgentType.TOOL_USE,
        system_prompt="You are a research assistant. Search for papers and summarize findings.",
        tool_names=["web_search", "arxiv_search"],
    ),
    AgentTemplate(
        id="agent-claude-code-001",
        name="Claude Code Agent",
        description="驱动 Claude Code CLI 完成复杂编程与脚本生成任务。",
        agent_type=AgentType.CLAUDE_CODE,
        system_prompt="You are a coding assistant powered by Claude Code.",
    ),
]


class MockMemoryDatabase(IAgentDatabase):
    def __init__(self) -> None:
        self._agents: Dict[str, AgentTemplate] = {a.id: a for a in _SEED_AGENTS}
        self._sessions: Dict[str, Session] = {}
        self._messages: Dict[str, List[Message]] = {}
        self._plugins: Dict[str, Plugin] = {}

    async def list_agents(self) -> List[AgentTemplate]:
        return list(self._agents.values())

    async def get_agent(self, agent_id: str) -> AgentTemplate:
        agent = self._agents.get(agent_id)
        if agent is None:
            raise KeyError(f"Agent '{agent_id}' not found")
        return agent

    async def create_session(self, agent_id: str, working_dir: str | None = None) -> Session:
        await self.get_agent(agent_id)  # validate agent exists
        session = Session(agent_id=agent_id, working_dir=working_dir)
        self._sessions[session.id] = session
        self._messages[session.id] = []
        return session

    async def get_session(self, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Session '{session_id}' not found")
        return session

    async def update_session_status(self, session_id: str, status: SessionStatus) -> Session:
        session = await self.get_session(session_id)
        session.status = status
        session.updated_at = datetime.now(timezone.utc)
        return session

    async def add_message(self, session_id: str, role: MessageRole, content: str) -> Message:
        await self.get_session(session_id)  # validate session exists
        message = Message(session_id=session_id, role=role, content=content)
        self._messages[session_id].append(message)
        return message

    async def get_messages(self, session_id: str) -> List[Message]:
        await self.get_session(session_id)
        return list(self._messages[session_id])

    # ------- Plugins -------

    async def list_plugins(self) -> List[Plugin]:
        return list(self._plugins.values())

    async def get_plugin(self, plugin_id: str) -> Plugin:
        plugin = self._plugins.get(plugin_id)
        if plugin is None:
            raise KeyError(f"Plugin '{plugin_id}' not found")
        return plugin

    async def create_plugin(self, name: str, code: str) -> Plugin:
        plugin = Plugin(name=name, code=code)
        self._plugins[plugin.id] = plugin
        return plugin

    async def update_plugin(
        self,
        plugin_id: str,
        *,
        name: str | None = None,
        code: str | None = None,
    ) -> Plugin:
        plugin = await self.get_plugin(plugin_id)
        if name is not None:
            plugin.name = name
        if code is not None:
            plugin.code = code
        plugin.updated_at = datetime.now(timezone.utc)
        return plugin

    async def delete_plugin(self, plugin_id: str) -> None:
        await self.get_plugin(plugin_id)
        del self._plugins[plugin_id]

    async def set_plugin_status(
        self,
        plugin_id: str,
        status: PluginStatus,
        *,
        exit_code: int | None = None,
        error: str | None = None,
    ) -> Plugin:
        plugin = await self.get_plugin(plugin_id)
        now = datetime.now(timezone.utc)
        plugin.status = status
        if status == PluginStatus.RUNNING:
            plugin.last_started_at = now
            plugin.last_exited_at = None
            plugin.last_exit_code = None
            plugin.last_error = None
        else:
            plugin.last_exited_at = now
            if exit_code is not None:
                plugin.last_exit_code = exit_code
            if error is not None:
                plugin.last_error = error
        plugin.updated_at = now
        return plugin
