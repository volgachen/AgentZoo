import os
import time
import uuid
from app.adapters.tools.base import BaseTool
from app.adapters.tools.registry import register_tool
from app.adapters.node_repl.registry import get_node_repl_registry

# Full results over this length spill to a log file (mirrors bash.py) so a huge
# console dump or return value doesn't blow up the ToolResult string.
_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "tmp", "node_repl")
_DEFAULT_MAX_OUTPUT = 8192
_DEFAULT_TIMEOUT = 120


def _log_path() -> str:
    os.makedirs(_LOG_DIR, exist_ok=True)
    name = f"node-{int(time.time())}-{uuid.uuid4().hex[:8]}.log"
    return os.path.abspath(os.path.join(_LOG_DIR, name))


def _truncate(text: str) -> str:
    if len(text) <= _DEFAULT_MAX_OUTPUT:
        return text
    path = _log_path()
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return (
        text[:_DEFAULT_MAX_OUTPUT]
        + f"\n\n[Truncated] Output exceeded {_DEFAULT_MAX_OUTPUT} characters "
        f"({len(text)} total). Full log saved to: {path}"
    )


class _NodeReplBase(BaseTool):
    """Shared plumbing: resolve the per-session Node subprocess and clean it up.

    The subprocess is keyed by session_id (fallback "default"), so js / reset /
    add_module_dir on the same session all drive one persistent context — which
    is what lets codex plugins keep globalThis.agent.browsers alive across turns.
    """

    def _key(self) -> str:
        return self.session_id or "default"

    def _session(self):
        return get_node_repl_registry().get_or_create(self._key(), self.working_dir)

    async def aclose(self) -> None:
        await get_node_repl_registry().close(self._key())


@register_tool
class NodeReplJsTool(_NodeReplBase):
    name = "node_repl_js"
    # Arbitrary code execution — same risk class as bash, so gate by default.
    requires_approval = True
    description = (
        "Execute JavaScript in a persistent Node.js REPL session (tool id "
        "'node_repl_js', a.k.a. mcp__node_repl__js). State persists across "
        "calls and turns: values assigned to globalThis (or globalThis.agent.*) "
        "survive between calls, while bare `const`/`let` do not. Supports "
        "top-level await and dynamic import() of ESM by absolute path. Use this "
        "to bootstrap and drive codex plugins (e.g. import a plugin's "
        "scripts/browser-client.mjs and call setupBrowserRuntime). The return "
        "value of the snippet and any console.log output are returned."
    )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "JavaScript to evaluate. Top-level await allowed.",
                },
                "timeout": {
                    "type": "number",
                    "description": f"Max seconds to run (default {_DEFAULT_TIMEOUT}).",
                },
            },
            "required": ["code"],
        }

    async def execute(self, code: str = "", timeout: float | None = None, **_) -> str:
        to = float(timeout) if timeout else _DEFAULT_TIMEOUT
        res = await self._session().request("eval", to, code=code)
        if not res.get("ok"):
            logs = "\n".join(res.get("logs") or [])
            prefix = (logs + "\n") if logs else ""
            return _truncate(f"{prefix}[error]\n{res.get('error', 'unknown error')}")
        parts = []
        logs = res.get("logs") or []
        if logs:
            parts.append("\n".join(logs))
        result = res.get("result", "undefined")
        parts.append(f"=> {result}")
        return _truncate("\n".join(parts))


@register_tool
class NodeReplResetTool(_NodeReplBase):
    name = "node_repl_reset"
    requires_approval = False
    description = (
        "Reset the persistent Node REPL session (tool id 'node_repl_reset', "
        "a.k.a. mcp__node_repl__js_reset): clears user-set globals so the next "
        "node_repl_js call starts from a clean context. Only clears state; use "
        "node_repl_js to run code."
    )

    def parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **_) -> str:
        res = await self._session().request("reset", 30)
        return res.get("result") if res.get("ok") else f"[error] {res.get('error')}"


@register_tool
class NodeReplAddModuleDirTool(_NodeReplBase):
    name = "node_repl_add_module_dir"
    requires_approval = False
    description = (
        "Add a directory to the Node REPL's module resolution paths (tool id "
        "'node_repl_add_module_dir', a.k.a. mcp__node_repl__js_add_node_module_dir) "
        "so require()/import of bare package names resolves against it — e.g. a "
        "codex plugin's scripts/node_modules. Only changes resolution; use "
        "node_repl_js to run code."
    )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "dir": {
                    "type": "string",
                    "description": "Absolute path to a node_modules-containing directory.",
                },
            },
            "required": ["dir"],
        }

    async def execute(self, dir: str = "", **_) -> str:
        resolved = self.resolve_path(dir)
        res = await self._session().request("add_module_dir", 30, dir=resolved)
        return res.get("result") if res.get("ok") else f"[error] {res.get('error')}"
