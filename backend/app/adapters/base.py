from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, AsyncGenerator
from pydantic import BaseModel

if TYPE_CHECKING:
    from app.models.domain import Message


class StreamEventType(str, Enum):
    USER = "user"
    TEXT = "text"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    STATUS = "status"
    ERROR = "error"
    DONE = "done"


class StreamEvent(BaseModel):
    type: StreamEventType
    data: str


class BaseAgentAdapter(ABC):
    session_id: str | None = None

    def __init__(self, session_id: str | None = None) -> None:
        # session_id is fixed at construction so tools that read it (e.g. the
        # subagent tool, which needs it as parent_session_id) see the real id
        # before start() runs — not None patched in later.
        self.session_id = session_id

    @abstractmethod
    async def start(self, system_prompt: str) -> None:
        """启动 Agent，建立底层进程或连接。"""

    @abstractmethod
    async def send(self, message: str) -> None:
        """向 Agent 发送用户消息。"""

    @abstractmethod
    async def stream(self) -> AsyncGenerator[StreamEvent, None]:
        """异步生成器，持续 yield StreamEvent 直到本轮结束（DONE）或出错。"""

    @abstractmethod
    async def stop(self) -> None:
        """终止 Agent，释放所有资源。"""

    async def restore_history(self, messages: "list[Message]") -> None:
        """Rebuild in-memory conversation state from persisted messages.

        Called when a session is rehydrated after a backend restart (the
        in-memory runner/adapter is gone but the DB rows survive). Default is a
        no-op; adapters that keep conversation history in process memory (e.g.
        OpenAI tool-use) override this so a resumed session isn't amnesiac.
        """
        return

    @property
    @abstractmethod
    def is_alive(self) -> bool:
        """Agent 进程/连接是否仍在运行。"""
