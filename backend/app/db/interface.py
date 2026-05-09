from abc import ABC, abstractmethod
from typing import List
from app.models.domain import AgentTemplate, Session, SessionStatus, Message, MessageRole


class IAgentDatabase(ABC):
    @abstractmethod
    async def list_agents(self) -> List[AgentTemplate]: pass

    @abstractmethod
    async def get_agent(self, agent_id: str) -> AgentTemplate: pass

    @abstractmethod
    async def create_session(self, agent_id: str, working_dir: str | None = None) -> Session: pass

    @abstractmethod
    async def get_session(self, session_id: str) -> Session: pass

    @abstractmethod
    async def update_session_status(self, session_id: str, status: SessionStatus) -> Session: pass

    @abstractmethod
    async def add_message(self, session_id: str, role: MessageRole, content: str) -> Message: pass

    @abstractmethod
    async def get_messages(self, session_id: str) -> List[Message]: pass
