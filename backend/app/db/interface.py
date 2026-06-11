from abc import ABC, abstractmethod
from typing import Any, List
from app.models.domain import (
    AgentTemplate, Session, SessionStatus, Message, MessageRole,
    Plugin, PluginStatus, Task, TaskStatus,
)

# Sentinel for update_task(owner=...) so callers can distinguish "leave owner
# unchanged" (the default) from "clear the owner" (explicitly passing None).
_UNSET: Any = object()


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

    # ------- Tasks -------
    @abstractmethod
    async def create_task(
        self,
        task_list_id: str,
        subject: str,
        description: str,
        *,
        active_form: str | None = None,
        metadata: dict | None = None,
    ) -> Task: pass

    @abstractmethod
    async def get_task(self, task_list_id: str, task_id: str) -> Task | None: pass

    @abstractmethod
    async def list_tasks(self, task_list_id: str) -> List[Task]: pass

    @abstractmethod
    async def update_task(
        self,
        task_list_id: str,
        task_id: str,
        *,
        subject: str | None = None,
        description: str | None = None,
        active_form: str | None = None,
        status: TaskStatus | None = None,
        owner: str | None = _UNSET,
        metadata: dict | None = None,
        add_blocks: list[str] | None = None,
        add_blocked_by: list[str] | None = None,
    ) -> Task | None: pass

    @abstractmethod
    async def delete_task(self, task_list_id: str, task_id: str) -> bool: pass

