import asyncio
import json
import shutil
import uuid
from typing import AsyncGenerator
from app.adapters.base import BaseAgentAdapter, StreamEvent, StreamEventType


class ClaudeCodeAdapter(BaseAgentAdapter):
    """
    Drives the `claude` CLI for one gateway session.

    Claude Code is single-turn: each invocation processes one stdin message
    then exits. We maintain conversation continuity via --session-id (first
    turn) and --resume (subsequent turns), letting Claude Code handle its own
    history on disk.
    """

    def __init__(self, working_dir: str | None = None) -> None:
        self._claude_session_id: str = str(uuid.uuid4())
        self._system_prompt: str = ""
        self._working_dir: str | None = working_dir
        self._turn_count: int = 0
        self._alive: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, system_prompt: str) -> None:
        claude_bin = shutil.which("claude")
        if claude_bin is None:
            raise RuntimeError("'claude' CLI not found in PATH")
        if self._working_dir is not None:
            import os
            if not os.path.isdir(self._working_dir):
                raise RuntimeError(f"working_dir does not exist: {self._working_dir}")
        self._system_prompt = system_prompt
        self._alive = True

    async def stop(self) -> None:
        self._alive = False

    # ------------------------------------------------------------------
    # Messaging + Streaming (combined per-turn)
    # ------------------------------------------------------------------

    async def send(self, message: str) -> None:
        """Queue a message; actual execution happens in stream()."""
        if not self._alive:
            raise RuntimeError("Adapter has been stopped")
        self._pending_message = message

    async def stream(self) -> AsyncGenerator[StreamEvent, None]:
        """
        Spawn a claude subprocess for the pending message and yield events.
        Yields STATUS/TEXT/TOOL_CALL events, then DONE or ERROR at the end.
        """
        message = getattr(self, "_pending_message", None)
        if message is None:
            return

        claude_bin = shutil.which("claude")
        args = [
            claude_bin,
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
        ]

        if self._turn_count == 0:
            args += ["--session-id", self._claude_session_id,
                     "--system-prompt", self._system_prompt]
        else:
            args += ["--resume", self._claude_session_id]

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._working_dir,
        )

        proc.stdin.write((message.strip() + "\n").encode())
        await proc.stdin.drain()
        proc.stdin.close()

        self._turn_count += 1

        try:
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode(errors="replace").strip()
                if not line:
                    continue
                for event in self._parse_line(line):
                    yield event
                    if event.type in (StreamEventType.DONE, StreamEventType.ERROR):
                        return
        finally:
            if proc.returncode is None:
                proc.terminate()
                await proc.wait()
            self._pending_message = None

        yield StreamEvent(type=StreamEventType.DONE, data="")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_line(line: str) -> list[StreamEvent]:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return [StreamEvent(type=StreamEventType.TEXT, data=line)]

        event_type = obj.get("type")

        if event_type == "system" and obj.get("subtype") == "init":
            return [StreamEvent(type=StreamEventType.STATUS, data="initialized")]

        if event_type == "assistant":
            events: list[StreamEvent] = []
            text_parts: list[str] = []
            for block in obj.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    text_parts.append(block["text"])
                elif block.get("type") == "tool_use":
                    if text_parts:
                        events.append(StreamEvent(type=StreamEventType.TEXT, data="".join(text_parts)))
                        text_parts = []
                    events.append(StreamEvent(
                        type=StreamEventType.TOOL_CALL,
                        data=f"[tool_use] {block.get('name')}({json.dumps(block.get('input', {}))})",
                    ))
            if text_parts:
                events.append(StreamEvent(type=StreamEventType.TEXT, data="".join(text_parts)))
            return events

        if event_type == "result":
            subtype = obj.get("subtype", "")
            if subtype == "success":
                return [StreamEvent(type=StreamEventType.DONE, data=obj.get("result", ""))]
            return [StreamEvent(type=StreamEventType.ERROR, data=obj.get("result", "error"))]

        return []

    @property
    def is_alive(self) -> bool:
        return self._alive
