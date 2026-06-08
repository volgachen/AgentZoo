import json
import logging
import os
import uuid
from pathlib import Path
import httpx
from app.adapters.tools.base import BaseTool
from app.adapters.tools.registry import register_tool

logger = logging.getLogger("agentzoo.tool.subagent")

_CREATE_SESSION_TIMEOUT = 30
_POST_MESSAGE_TIMEOUT = 15

# Where isolated working directories live for "worktree" isolation.
_WORKTREE_ROOT = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "tmp", "sessions"
)


@register_tool
class SubagentTool(BaseTool):
    name = "subagent"
    description = (
        "Launch a new subagent session to handle a complex, multi-step task "
        "in the background. The subagent runs independently — you get back a "
        "session ID immediately and continue your work without waiting.\n\n"
        "When the subagent finishes, it will POST its results back to your "
        "session automatically (your session ID is included as parent_session_id).\n\n"
        "Available agent templates (pass as agent_id):\n"
        "- agent-claude-code-001: Claude Code agent with full CLI toolset\n"
        "- agent-research-001: OpenAI tool-use agent with web_fetch, web_search, "
        "bash, read, write, edit\n\n"
        "Choose isolation=\"worktree\" when the subagent needs its own isolated "
        "working directory (recommended for Claude Code agents). Omit isolation "
        "to share the parent context."
    )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": (
                        "Agent template ID. Available: 'agent-claude-code-001' "
                        "(Claude Code CLI) or 'agent-research-001' (OpenAI tool-use)."
                    ),
                },
                "task": {
                    "type": "string",
                    "description": (
                        "The task for the subagent to perform. Be specific — include "
                        "what to do, what output format you expect, and any "
                        "constraints. This is sent as the first message."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "Short label (3-5 words) describing the task, for logging.",
                },
                "isolation": {
                    "type": "string",
                    "description": (
                        "'worktree' creates an isolated working directory for the "
                        "subagent under backend/tmp/sessions/. Omit to run without "
                        "filesystem isolation (tool-use agents don't need it)."
                    ),
                    "enum": ["worktree"],
                },
            },
            "required": ["agent_id", "task"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        agent_id: str,
        task: str,
        description: str | None = None,
        isolation: str | None = None,
    ) -> str:
        parent_session_id = self.session_id
        gateway_url = os.getenv("GATEWAY_URL", "http://localhost:12598")
        base = gateway_url.rstrip("/")

        # ---- Build create-session body ----
        body: dict = {"agent_id": agent_id}
        if parent_session_id:
            body["parent_session_id"] = parent_session_id

        work_dir: str | None = None
        if isolation == "worktree":
            work_dir = os.path.abspath(
                os.path.join(_WORKTREE_ROOT, str(uuid.uuid4()))
            )
            os.makedirs(work_dir, exist_ok=False)
            body["working_dir"] = work_dir
            logger.info("worktree isolation: work_dir=%s", work_dir)

        label = description or f"subagent:{agent_id}"
        logger.info(
            "launching %s agent=%s parent=%s isolation=%s",
            label, agent_id, parent_session_id, isolation or "none",
        )

        # ---- 1) Create the session ----
        try:
            async with httpx.AsyncClient(timeout=_CREATE_SESSION_TIMEOUT) as client:
                resp = await client.post(
                    f"{base}/api/v1/sessions",
                    headers={"content-type": "application/json"},
                    content=json.dumps(body),
                )
        except httpx.TimeoutException:
            return "Error: Gateway timeout while creating subagent session."
        except httpx.ConnectError:
            return (
                f"Error: Cannot connect to gateway at {gateway_url}. "
                "Is AgentZoo running?"
            )
        except Exception as e:
            logger.exception("unexpected error creating subagent session")
            return f"Error: Unexpected error creating subagent session: {e}"

        if resp.status_code != 201:
            return self._format_create_error(resp, agent_id, parent_session_id)

        session = resp.json()
        new_id = session["id"]
        logger.info("subagent session created id=%s label=%s", new_id, label)

        # ---- 2) Send the first task ----
        msg_body = {"content": task}
        try:
            async with httpx.AsyncClient(timeout=_POST_MESSAGE_TIMEOUT) as client:
                msg_resp = await client.post(
                    f"{base}/api/v1/sessions/{new_id}/messages",
                    headers={"content-type": "application/json"},
                    content=json.dumps(msg_body),
                )
        except httpx.TimeoutException:
            return (
                f"Session created (id={new_id}) but posting the first message "
                f"timed out. The session exists but has no task yet."
            )
        except Exception as e:
            logger.exception("unexpected error posting first message to %s", new_id)
            return (
                f"Session created (id={new_id}) but posting the first message "
                f"failed: {e}. The session exists but has no task yet."
            )

        if msg_resp.status_code != 202:
            body_text = msg_resp.text
            logger.warning(
                "post message returned %d for session=%s: %s",
                msg_resp.status_code, new_id, body_text,
            )
            return (
                f"Session created (id={new_id}) but posting first message returned "
                f"{msg_resp.status_code}: {body_text[:300]}. "
                "The session may not have received the task."
            )

        # ---- Result ----
        lines = [
            f"Subagent launched: {label}",
            f"  session_id: {new_id}",
        ]
        if parent_session_id:
            lines.append(
                f"  parent_session_id: {parent_session_id} "
                "(results will be reported back to you when done)"
            )
        lines.append(f"  agent_id: {agent_id}")
        if isolation:
            lines.append(f"  isolation: {isolation}")
        if work_dir:
            lines.append(f"  working_dir: {work_dir}")
        lines.append("")
        lines.append(f"Check progress: GET {base}/api/v1/sessions/{new_id}")
        lines.append(f"Send follow-up: POST {base}/api/v1/sessions/{new_id}/messages")

        return "\n".join(lines)

    @staticmethod
    def _format_create_error(
        resp: httpx.Response, agent_id: str, parent_session_id: str | None
    ) -> str:
        detail = "unknown error"
        try:
            detail = resp.json().get("detail", detail)
        except Exception:
            detail = resp.text[:500]

        if resp.status_code == 404:
            return (
                f"Error: {detail} (agent_id='{agent_id}' or "
                f"parent_session_id='{parent_session_id}' not found)."
            )
        if resp.status_code == 400:
            return f"Error: {detail}"
        if resp.status_code == 409:
            return f"Error: {detail}"
        logger.error("create session failed status=%d body=%s", resp.status_code, detail)
        return f"Error: Gateway returned {resp.status_code}: {detail}"
