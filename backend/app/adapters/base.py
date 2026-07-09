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
    # Emitted before a tool that isn't auto-approved runs; the adapter blocks on
    # a human decision routed back via resolve_decision. data is JSON
    # {call_id, name, args}.
    TOOL_CONFIRM = "tool_confirm"
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

    async def resolve_decision(self, call_id: str, approved: bool) -> None:
        """Resolve a pending tool-confirm request (see TOOL_CONFIRM).

        Called by the runner when a human approves/denies a tool call the
        adapter is blocked on. Default is a no-op — adapters that don't gate
        tools (e.g. Claude Code, whose tools run in the CLI subprocess with its
        own permission flow) simply ignore it.
        """
        return

    @property
    @abstractmethod
    def is_alive(self) -> bool:
        """Agent 进程/连接是否仍在运行。"""
