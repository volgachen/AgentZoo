import asyncio
import json
import os
import signal
import uuid

# Path to the persistent REPL server we spawn per session.
_SERVER = os.path.join(os.path.dirname(__file__), "server.mjs")

# Node runtime: configurable via NODE_BIN (see CLAUDE.md persistence/env notes),
# falling back to `node` on PATH.
def _node_bin() -> str:
    return os.getenv("NODE_BIN") or "node"


class NodeReplSession:
    """Owns one long-lived Node subprocess for a single AgentZoo session.

    The codex plugins stash browser runtime state under globalThis.agent and
    reuse it across turns, so unlike bash (fresh subprocess per call) we keep the
    process alive for the session's lifetime. All three node_repl tools share the
    same instance via NodeReplRegistry, so `js`, `js_reset`, and
    `js_add_node_module_dir` operate on the same context.
    """

    def __init__(self, working_dir: str | None) -> None:
        self._working_dir = working_dir
        self._proc: asyncio.subprocess.Process | None = None
        # Requests are serialized: the OpenAI tool loop executes tool calls one
        # at a time, and the server handles one request per line anyway.
        self._lock = asyncio.Lock()

    async def _ensure(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            return
        self._proc = await asyncio.create_subprocess_exec(
            _node_bin(),
            _SERVER,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=self._working_dir or None,
            # Own process group so stop() can SIGTERM the whole tree (the plugins
            # may spawn child processes, e.g. a browser host).
            start_new_session=True,
        )
        # Drain the initial {"ready":true} banner.
        assert self._proc.stdout is not None
        await asyncio.wait_for(self._proc.stdout.readline(), timeout=30)

    async def request(self, op: str, timeout: float, **fields) -> dict:
        async with self._lock:
            try:
                await self._ensure()
            except FileNotFoundError:
                return {
                    "ok": False,
                    "error": (
                        f"Node runtime not found (tried '{_node_bin()}'). Set NODE_BIN "
                        f"to a Node executable, or install Node.js on the server."
                    ),
                }
            assert self._proc is not None and self._proc.stdin and self._proc.stdout
            req_id = uuid.uuid4().hex[:8]
            payload = {"id": req_id, "op": op, "timeout_ms": int(timeout * 1000), **fields}
            self._proc.stdin.write((json.dumps(payload) + "\n").encode())
            await self._proc.stdin.drain()
            try:
                # Give the process a little slack beyond the in-VM eval timeout so
                # the server's own timeout error can come back cleanly.
                line = await asyncio.wait_for(
                    self._proc.stdout.readline(), timeout=timeout + 15
                )
            except asyncio.TimeoutError:
                await self.stop()
                return {
                    "ok": False,
                    "error": f"node_repl unresponsive after {timeout}s; process restarted.",
                }
            if not line:
                return {"ok": False, "error": "node_repl process exited unexpectedly."}
            try:
                return json.loads(line.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                return {"ok": False, "error": f"bad response from node_repl: {line!r}"}

    async def stop(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None or proc.returncode is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            await proc.wait()


class NodeReplRegistry:
    """session_id -> NodeReplSession. In-memory singleton, mirroring
    AdapterRegistry: does not survive a backend restart."""

    def __init__(self) -> None:
        self._sessions: dict[str, NodeReplSession] = {}

    def get_or_create(self, key: str, working_dir: str | None) -> NodeReplSession:
        sess = self._sessions.get(key)
        if sess is None:
            sess = NodeReplSession(working_dir)
            self._sessions[key] = sess
        return sess

    async def close(self, key: str) -> None:
        sess = self._sessions.pop(key, None)
        if sess is not None:
            await sess.stop()


_registry = NodeReplRegistry()


def get_node_repl_registry() -> NodeReplRegistry:
    return _registry
