"""WebSocket end-to-end for the tool-use adapter.

Requires uvicorn running AND OPENAI_API_KEY (and optionally OPENAI_BASE_URL /
OPENAI_MODEL) in the backend `.env`.

Uses the Research Agent seed and prompts it for a topic that should trigger
arxiv_search / web_search. Asserts we see at least one TOOL_CALL followed by
a final TEXT event before DONE.
"""
import asyncio
import json
import os
import sys

import httpx
import websockets

from _common import BASE_URL, WS_BASE_URL, ok, fail, info, section

AGENT_ID = "agent-research-001"
PROMPT = "Find one recent arxiv paper about transformer efficiency and summarize it in one sentence."


async def drain_turn(ws) -> tuple[list[str], list[str], str]:
    texts: list[str] = []
    tool_calls: list[str] = []
    terminal = ""
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=180)
        evt = json.loads(raw)
        et = evt.get("type")
        if et == "session_state":
            info(f"session_state -> status={evt['data'].get('status')}")
            continue
        if et == "text":
            texts.append(evt["data"])
            info(f"text: {evt['data'][:100]}")
            continue
        if et == "tool_call":
            tool_calls.append(evt["data"])
            info(f"tool_call: {evt['data'][:120]}")
            continue
        if et in ("done", "error"):
            terminal = et
            info(f"{et}: {str(evt['data'])[:120]}")
            return texts, tool_calls, terminal


async def main() -> int:
    section("WebSocket end-to-end (OpenAI tool-use adapter)")

    if not os.getenv("OPENAI_API_KEY"):
        info("Note: OPENAI_API_KEY not set in this shell. The backend reads .env on startup,")
        info("so this script only warns — it does not block. The adapter will fail loudly")
        info("if the backend itself lacks the key.")

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
            await ws.send(json.dumps({"content": PROMPT}))
            texts, tool_calls, terminal = await drain_turn(ws)
            if terminal != "done":
                fail(f"turn ended with {terminal}")
                return 1
            if not tool_calls:
                fail("no TOOL_CALL events — the model did not invoke any tool")
                return 1
            if not texts:
                fail("no TEXT events — model produced no final answer")
                return 1
            ok(f"turn completed: {len(texts)} text, {len(tool_calls)} tool_call")
    except Exception as e:
        fail(f"WebSocket error: {e}")
        return 1
    finally:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            await c.delete(f"/api/v1/sessions/{session_id}")

    print("\nTool-use WS round-trip OK.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
