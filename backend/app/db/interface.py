from abc import ABC, abstractmethod
from typing import List
from app.models.domain import (
    AgentTemplate, Session, SessionStatus, Message, MessageRole,
    Plugin, PluginStatus,
)


class IAgentDatabase(ABC):
    @abstractmethod
    async def list_agents(self) -> List[AgentTemplate]: pass

    @abstractmethod
    async def get_agent(self, agent_id: str) -> AgentTemplate: pass

    @abstractmethod
    async def create_agent(self, template: AgentTemplate) -> AgentTemplate: pass

    @abstractmethod
    async def update_agent(
        self,
        agent_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        system_prompt: str | None = None,
        tool_names: list[str] | None = None,
        openai_model: str | None = None,
        openai_base_url: str | None = None,
    ) -> AgentTemplate: pass

    @abstractmethod
    async def delete_agent(self, agent_id: str) -> None: pass

    @abstractmethod
    async def create_session(
        self,
        agent_id: str,
        working_dir: str | None = None,
        *,
        parent_session_id: str | None = None,
    ) -> Session: pass

    @abstractmethod
    async def get_session(self, session_id: str) -> Session: pass

    @abstractmethod
    async def list_sessions(self) -> List[Session]: pass

    @abstractmethod
    async def update_session_status(self, session_id: str, status: SessionStatus) -> Session: pass

    @abstractmethod
    async def add_message(
        self,
        session_id: str,
        role: MessageRole,
        content: str,
        *,
        from_session_id: str | None = None,
    ) -> Message: pass

    @abstractmethod
    async def get_messages(self, session_id: str) -> List[Message]: pass

    # ------- Plugins -------
    @abstractmethod
    async def list_plugins(self) -> List[Plugin]: pass

    @abstractmethod
    async def get_plugin(self, plugin_id: str) -> Plugin: pass

    @abstractmethod
    async def create_plugin(self, name: str, code: str) -> Plugin: pass

    @abstractmethod
    async def update_plugin(
        self,
        plugin_id: str,
        *,
        name: str | None = None,
        code: str | None = None,
    ) -> Plugin: pass

    @abstractmethod
    async def delete_plugin(self, plugin_id: str) -> None: pass

    @abstractmethod
    async def set_plugin_status(
        self,
        plugin_id: str,
        status: PluginStatus,
        *,
        exit_code: int | None = None,
        error: str | None = None,
    ) -> Plugin: pass
