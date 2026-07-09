"""Drive the tool-confirm flow end-to-end against a running gateway.

Creates a tool_use session, opens its WS, sends a prompt that should trigger a
gated tool (write), and asserts a tool_confirm frame arrives — then approves it
and watches the tool run. Run against a live backend (DB_TYPE=mock is fine):

    python -m uvicorn app.main:app --host 127.0.0.1 --port 12598  # in another shell
    python scripts/test_confirm_flow.py
"""
import asyncio
import json
import os
import sys

import httpx
import websockets

BASE = "http://127.0.0.1:12598/api/v1"
WS = "ws://127.0.0.1:12598/api/v1"
AGENT = "agent-research-001"  # research agent: gates write/edit/session_send


async def main(approve: bool) -> None:
    async with httpx.AsyncClient(trust_env=False, timeout=30) as c:
        # Fresh working dir so the write tool has somewhere to land.
        wd = "E:/Projects/AgentZoo/backend/tmp/confirm_test_wd"
        os.makedirs(wd, exist_ok=True)
        r = await c.post(
            f"{BASE}/sessions",
            json={"agent_id": AGENT, "working_dir": wd},
        )
        r.raise_for_status()
        sid = r.json()["id"]
        print(f"[created] session={sid} status={r.json()['status']}")

    uri = f"{WS}/sessions/{sid}/stream"
    async with websockets.connect(uri, max_size=None) as ws:
        # First frame is session_state.
        state = json.loads(await ws.recv())
        print(f"[ws] {state['type']} status={state['data']['status']}")

        prompt = (
            "Use the write tool to create a file named hello.txt containing the "
            "text 'hi from confirm test'. Do it now with the write tool."
        )
        await ws.send(json.dumps({"content": prompt}))
        print(f"[sent] {prompt!r}")

        saw_confirm = False
        saw_result = False
        deadline = asyncio.get_event_loop().time() + 90
        while asyncio.get_event_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=90)
            except asyncio.TimeoutError:
                print("[timeout] no more frames")
                break
            frame = json.loads(raw)
            t = frame["type"]
            data = frame.get("data", "")
            short = data if len(str(data)) < 200 else str(data)[:200] + "…"
            print(f"[ws] {t}: {short}")

            if t == "tool_confirm":
                saw_confirm = True
                obj = json.loads(data)
                print(f"  >>> CONFIRM REQUESTED for {obj['name']} call_id={obj['call_id']}")
                decision = "approve" if approve else "deny"
                await ws.send(json.dumps({"decision": decision, "call_id": obj["call_id"]}))
                print(f"  <<< sent decision={decision}")
            elif t == "tool_result":
                saw_result = True
            elif t in ("done", "error"):
                print(f"[end] {t}")
                break

        print("\n==== RESULT ====")
        print(f"saw tool_confirm: {saw_confirm}")
        print(f"saw tool_result:  {saw_result}")
        if not saw_confirm:
            print("FAIL: no tool_confirm frame — model may not have called a gated tool")
            sys.exit(2)
        print("PASS")


if __name__ == "__main__":
    approve = "--deny" not in sys.argv
    asyncio.run(main(approve))
