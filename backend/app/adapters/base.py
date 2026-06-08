from abc import ABC, abstractmethod
from enum import Enum
from typing import AsyncGenerator
from pydantic import BaseModel


class StreamEventType(str, Enum):
    USER = "user"
    TEXT = "text"
    TOOL_CALL = "tool_call"
    STATUS = "status"
    ERROR = "error"
    DONE = "done"


class StreamEvent(BaseModel):
    type: StreamEventType
    data: str


class BaseAgentAdapter(ABC):
    session_id: str | None = None

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

    @property
    @abstractmethod
    def is_alive(self) -> bool:
        """Agent 进程/连接是否仍在运行。"""
