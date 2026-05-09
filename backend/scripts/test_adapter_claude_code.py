"""Drive ClaudeCodeAdapter directly — no uvicorn, no router.

Requires the `claude` CLI in PATH. Exercises the full adapter lifecycle across
two turns to verify --session-id / --resume continuity works in isolation.
"""
import asyncio
import shutil
import sys

import _common  # noqa: F401

from app.adapters.claude_code import ClaudeCodeAdapter
from app.adapters.base import StreamEventType
from _common import ok, fail, info, section

PROMPTS = [
    "Reply with only the word: ping",
    "Reply with only the word: pong",
]


async def run_turn(adapter: ClaudeCodeAdapter, prompt: str, idx: int) -> bool:
    info(f"--- turn {idx}: {prompt!r} ---")
    await adapter.send(prompt)
    got_text = False
    got_terminal = False
    async for event in adapter.stream():
        if event.type == StreamEventType.TEXT:
            got_text = True
            info(f"text: {event.data[:80]}")
        elif event.type == StreamEventType.TOOL_CALL:
            info(f"tool_call: {event.data[:80]}")
        elif event.type == StreamEventType.STATUS:
            info(f"status: {event.data}")
        elif event.type == StreamEventType.DONE:
            info(f"done: {event.data[:80]}")
            got_terminal = True
            break
        elif event.type == StreamEventType.ERROR:
            fail(f"error: {event.data[:120]}")
            return False
    if not got_terminal:
        fail(f"turn {idx} stream ended without DONE")
        return False
    if not got_text:
        fail(f"turn {idx} produced no TEXT events")
        return False
    ok(f"turn {idx} completed")
    return True


async def main() -> int:
    section("ClaudeCodeAdapter direct-drive")
    if shutil.which("claude") is None:
        fail("'claude' CLI not found in PATH")
        return 2

    adapter = ClaudeCodeAdapter()
    try:
        await adapter.start("You are a terse assistant. Reply with one word only.")
    except RuntimeError as e:
        fail(f"start failed: {e}")
        return 1

    try:
        for i, p in enumerate(PROMPTS, 1):
            if not await run_turn(adapter, p, i):
                return 1
    finally:
        await adapter.stop()

    print("\nClaudeCodeAdapter direct-drive OK.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
