"""WebSocket end-to-end — requires uvicorn running AND `claude` CLI in PATH.

Creates a Claude Code session, sends two prompts in sequence to exercise
--session-id / --resume continuity, and asserts at least one TEXT event per turn.
"""
import asyncio
import json
import shutil
import sys

import httpx
import websockets

from _common import BASE_URL, WS_BASE_URL, ok, fail, info, section

AGENT_ID = "agent-claude-code-001"
PROMPTS = [
    "Reply with the single word: hello",
    "Now reply with the single word: world",
]


async def drain_turn(ws) -> tuple[list[str], list[str], str]:
    """Collect events until DONE or ERROR. Returns (texts, tool_calls, terminal)."""
    texts: list[str] = []
    tool_calls: list[str] = []
    terminal = ""
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=120)
        evt = json.loads(raw)
        et = evt.get("type")
        if et == "session_state":
            info(f"session_state -> status={evt['data'].get('status')}")
            continue
        if et == "status":
            info(f"status: {evt['data']}")
            continue
        if et == "text":
            texts.append(evt["data"])
            info(f"text: {evt['data'][:80]}")
            continue
        if et == "tool_call":
            tool_calls.append(evt["data"])
            info(f"tool_call: {evt['data'][:80]}")
            continue
        if et in ("done", "error"):
            terminal = et
            info(f"{et}: {evt['data'][:120]}")
            return texts, tool_calls, terminal
    return texts, tool_calls, terminal  # unreachable


async def main() -> int:
    section("WebSocket end-to-end (Claude Code adapter)")

    if shutil.which("claude") is None:
        fail("'claude' CLI not found in PATH — install it before running this script")
        return 2

    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as c:
            r = await c.post("/api/v1/sessions", json={"agent_id": AGENT_ID})
            if r.status_code != 201:
                fail(f"create session -> {r.status_code}: {r.text}")
                return 1
            session_id = r.json()["id"]
            ok(f"session created: {session_id}")
    except httpx.ConnectError as e:
        fail(f"Cannot reach {BASE_URL} — is uvicorn running? ({e})")
        return 2

    ws_url = f"{WS_BASE_URL}/api/v1/sessions/{session_id}/stream"
    info(f"connecting to {ws_url}")

    try:
        async with websockets.connect(ws_url, max_size=None) as ws:
            for i, prompt in enumerate(PROMPTS, 1):
                info(f"--- turn {i}: {prompt!r} ---")
                await ws.send(json.dumps({"content": prompt}))
                texts, tool_calls, terminal = await drain_turn(ws)
                if terminal != "done":
                    fail(f"turn {i} ended with {terminal}")
                    return 1
                if not texts:
                    fail(f"turn {i} produced no TEXT events")
                    return 1
                ok(f"turn {i} completed: {len(texts)} text, {len(tool_calls)} tool_call")
    except Exception as e:
        fail(f"WebSocket error: {e}")
        return 1
    finally:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            await c.delete(f"/api/v1/sessions/{session_id}")

    print("\nClaude Code WS round-trip OK.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
