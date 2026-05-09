"""Drive OpenAIToolUseAdapter directly — no uvicorn, no router.

Loads .env (same file the backend reads) so OPENAI_* work. Uses web_search and
arxiv_search with a prompt that should trigger at least one tool call.
"""
import asyncio
import os
import sys
from pathlib import Path

import _common  # noqa: F401 — sets sys.path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.adapters.openai_tool_use import OpenAIToolUseAdapter
from app.adapters.base import StreamEventType
from _common import ok, fail, info, section

PROMPT = "Find one recent arxiv paper about transformer efficiency and summarize it in one sentence."


async def main() -> int:
    section("OpenAIToolUseAdapter direct-drive")

    if not os.getenv("OPENAI_API_KEY"):
        fail("OPENAI_API_KEY not set (neither in shell nor in backend/.env)")
        return 2

    adapter = OpenAIToolUseAdapter(
        tool_names=["web_search", "arxiv_search"],
        model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        base_url=os.getenv("OPENAI_BASE_URL"),
    )
    try:
        await adapter.start("You are a research assistant. Use tools to find papers.")
    except (ValueError, RuntimeError) as e:
        fail(f"start failed: {e}")
        return 1

    try:
        await adapter.send(PROMPT)
        texts: list[str] = []
        tool_calls: list[str] = []
        terminal: str | None = None
        async for event in adapter.stream():
            if event.type == StreamEventType.TEXT:
                texts.append(event.data)
                info(f"text: {event.data[:100]}")
            elif event.type == StreamEventType.TOOL_CALL:
                tool_calls.append(event.data)
                info(f"tool_call: {event.data[:120]}")
            elif event.type == StreamEventType.DONE:
                terminal = "done"
                break
            elif event.type == StreamEventType.ERROR:
                fail(f"error: {event.data[:120]}")
                return 1

        if terminal != "done":
            fail(f"stream ended without DONE (terminal={terminal})")
            return 1
        if not tool_calls:
            fail("no TOOL_CALL events — model did not invoke any tool")
            return 1
        if not texts:
            fail("no TEXT events — no final answer")
            return 1
        ok(f"completed: {len(texts)} text, {len(tool_calls)} tool_call")
    finally:
        await adapter.stop()

    print("\nOpenAIToolUseAdapter direct-drive OK.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
