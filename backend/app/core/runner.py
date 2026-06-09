import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from app.adapters.base import BaseAgentAdapter, StreamEvent, StreamEventType
from app.db.interface import IAgentDatabase
from app.models.domain import MessageRole, SessionStatus

logger = logging.getLogger("agentzoo.runner")

_SUBSCRIBER_QUEUE_MAX = 256


@dataclass
class _InboxItem:
    content: str
    from_session_id: str | None = None


class SessionRunner:
    """Owns a single adapter and serializes turns through it.

    The adapter contract is single-consumer (`send` then iterate `stream`),
    so we can't let WS handlers and HTTP handlers both drive it. The runner
    is the one consumer; everyone else is a producer (`submit`) or a
    subscriber (`subscribe`). This is what makes HTTP-initiated turns
    visible to dashboard WS clients.
    """

    def __init__(
        self,
        session_id: str,
        adapter: BaseAgentAdapter,
        db: IAgentDatabase,
    ) -> None:
        self._session_id = session_id
        self._adapter = adapter
        self._db = db
        self._inbox: asyncio.Queue[_InboxItem] = asyncio.Queue()
        self._subscribers: set[asyncio.Queue[StreamEvent | None]] = set()
        self._task: asyncio.Task | None = None
        self._generating = False

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name=f"runner:{self._session_id}")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("runner task crashed during stop session=%s", self._session_id)
            self._task = None

        for q in list(self._subscribers):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass
        self._subscribers.clear()

        try:
            await self._adapter.stop()
        except Exception:
            logger.exception("adapter.stop raised session=%s", self._session_id)

    async def submit(self, content: str, from_session_id: str | None = None) -> None:
        await self._inbox.put(_InboxItem(content=content, from_session_id=from_session_id))

    @property
    def is_generating(self) -> bool:
        return self._generating

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[AsyncIterator[StreamEvent]]:
        q: asyncio.Queue[StreamEvent | None] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_MAX)
        self._subscribers.add(q)
        try:
            yield self._iter(q)
        finally:
            self._subscribers.discard(q)

    async def _iter(self, q: asyncio.Queue[StreamEvent | None]) -> AsyncIterator[StreamEvent]:
        while True:
            ev = await q.get()
            if ev is None:
                return
            yield ev

    def _broadcast(self, event: StreamEvent) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "subscriber queue full session=%s dropping %s",
                    self._session_id, event.type,
                )

    async def _loop(self) -> None:
        while True:
            item = await self._inbox.get()
            await self._db.update_session_status(self._session_id, SessionStatus.RUNNING)
            try:
                await self._run_turn(item)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("runner turn crashed session=%s", self._session_id)
                self._broadcast(StreamEvent(type=StreamEventType.ERROR, data=str(e)))
                self._generating = False
                try:
                    await self._db.update_session_status(self._session_id, SessionStatus.ERROR)
                except Exception:
                    logger.exception("failed to mark session ERROR session=%s", self._session_id)

    async def _run_turn(self, item: _InboxItem) -> None:
        # Persist the raw content + sender separately; the agent stdin gets a
        # prefixed view so it can route its reply.
        await self._db.add_message(
            self._session_id,
            MessageRole.USER,
            item.content,
            from_session_id=item.from_session_id,
        )
        delivered = (
            f"[from-session:{item.from_session_id}] {item.content}"
            if item.from_session_id
            else item.content
        )
        self._broadcast(StreamEvent(type=StreamEventType.USER, data=delivered))

        self._generating = True
        agent_buf: list[str] = []
        errored = False
        try:
            await self._adapter.send(delivered)
            async for event in self._adapter.stream():
                self._broadcast(event)
                if event.type == StreamEventType.TEXT:
                    agent_buf.append(event.data)
                elif event.type == StreamEventType.TOOL_CALL:
                    # Persist tool interactions as their own rows so history
                    # (not just the live stream) shows what the agent did.
                    await self._db.add_message(
                        self._session_id, MessageRole.TOOL_CALL, event.data
                    )
                elif event.type == StreamEventType.TOOL_RESULT:
                    await self._db.add_message(
                        self._session_id, MessageRole.TOOL, event.data
                    )
                elif event.type == StreamEventType.ERROR:
                    errored = True
        finally:
            self._generating = False

        if agent_buf:
            await self._db.add_message(
                self._session_id, MessageRole.AGENT, "\n".join(agent_buf)
            )
        if errored:
            await self._db.update_session_status(self._session_id, SessionStatus.ERROR)
        else:
            await self._db.update_session_status(self._session_id, SessionStatus.WAITING_USER)
