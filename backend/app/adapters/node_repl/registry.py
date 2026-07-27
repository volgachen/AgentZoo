import asyncio
import glob
import json
import os
import signal
import uuid

# Path to the persistent REPL server we spawn per session.
_SERVER = os.path.join(os.path.dirname(__file__), "server.mjs")


def _latest(pattern: str) -> str | None:
    hits = sorted(glob.glob(pattern))
    # The plugin cache keeps a `latest` alias beside the versioned dirs; trust it
    # over lexical version ordering when it's there.
    for hit in hits:
        if os.path.basename(hit.rstrip("/\\")) == "latest":
            return hit.replace("\\", "/")
    return hits[-1].replace("\\", "/") if hits else None


def codex_plugin_root(name: str = "chrome") -> str | None:
    """Locate a bundled codex desktop plugin. Version dirs change on every
    desktop-app update, so always scan (docs/codex_chrome/pitfalls.md #12)."""
    home = os.path.expanduser("~")
    return _latest(f"{home}/.codex/plugins/cache/openai-bundled/{name}/*")


def _codex_runtime_modules() -> str | None:
    home = os.path.expanduser("~")
    return _latest(f"{home}/AppData/Local/OpenAI/Codex/runtimes/cua_node/*/bin/node_modules")


def _codex_runtime_node() -> str | None:
    """Node shipped with the Codex/ChatGPT desktop app, if installed.

    Preferred for codex plugins: its bundled node_modules carry prebuilt native
    modules (sharp, @napi-rs/canvas, playwright) compiled against exactly this
    ABI, so a different Node major fails to load them. The hash directory changes
    on every desktop-app update — always scan, never hardcode.
    """
    home = os.path.expanduser("~")
    exe = "node.exe" if os.name == "nt" else "node"
    hits = sorted(
        glob.glob(os.path.join(home, "AppData/Local/OpenAI/Codex/runtimes/cua_node/*/bin", exe))
        or glob.glob(os.path.join(home, ".codex/runtimes/cua_node/*/bin", exe))
    )
    return hits[-1] if hits else None


# Node runtime: explicit NODE_BIN wins, then the codex desktop runtime (ABI-matched
# for the bundled plugins), then plain `node` on PATH.
def _node_bin() -> str:
    override = (os.getenv("NODE_BIN") or "").strip()
    # A NODE_BIN that names a path which doesn't exist is almost always a quoting
    # accident (dotenv expands \r \f \b \n inside double quotes, which mangles
    # Windows paths). Prefer autodetection over failing every call.
    if override and (os.path.isfile(override) or os.sep not in override):
        return override
    return _codex_runtime_node() or override or "node"


class NodeReplSession:
    """Owns one long-lived Node subprocess for a single AgentZoo session.

    The codex plugins stash browser runtime state under globalThis.agent and
    reuse it across turns, so unlike bash (fresh subprocess per call) we keep the
    process alive for the session's lifetime. All three node_repl tools share the
    same instance via NodeReplRegistry, so `js`, `js_reset`, and
    `js_add_node_module_dir` operate on the same context.
    """

    def __init__(self, working_dir: str | None, session_key: str = "default") -> None:
        self._working_dir = working_dir
        self._session_key = session_key
        self._proc: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stderr_tail: list[str] = []
        # Requests are serialized: the OpenAI tool loop executes tool calls one
        # at a time, and the server handles one request per line anyway.
        self._lock = asyncio.Lock()

    async def _ensure(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            return
        env = dict(os.environ)
        # The codex plugin host shim scopes browser tab ownership by this id; it
        # must be stable for the life of the session or tabs.list() comes back
        # empty on every turn.
        env["AGENTZOO_SESSION_ID"] = self._session_key
        self._proc = await asyncio.create_subprocess_exec(
            _node_bin(),
            _SERVER,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            # stdout is the NDJSON protocol channel — keep stderr on its own pipe
            # so a plugin-spawned child process (which inherits fd 2) can't inject
            # lines into it. Must be drained, or a chatty child fills the pipe
            # buffer and blocks.
            stderr=asyncio.subprocess.PIPE,
            cwd=self._working_dir or None,
            # Own process group so stop() can SIGTERM the whole tree (the plugins
            # may spawn child processes, e.g. a browser host).
            start_new_session=True,
        )
        self._stderr_tail = []
        self._stderr_task = asyncio.create_task(self._drain_stderr(self._proc))
        # Drain the initial {"ready":true} banner.
        assert self._proc.stdout is not None
        await asyncio.wait_for(self._proc.stdout.readline(), timeout=30)
        await self._preload_module_dirs()

    async def _preload_module_dirs(self) -> None:
        """Pre-register the codex plugin + runtime node_modules.

        The plugins import bare package names from both trees, and the runtime one
        holds prebuilt natives (sharp / canvas / playwright). Doing it here means an
        agent following the plugin's SKILL.md verbatim just works, instead of first
        having to discover two version-stamped paths.
        """
        dirs = []
        root = codex_plugin_root("chrome")
        if root:
            dirs.append(f"{root}/scripts/node_modules")
        runtime = _codex_runtime_modules()
        if runtime:
            dirs.append(runtime)
        for d in dirs:
            if not os.path.isdir(d):
                continue
            await self._request_locked("add_module_dir", 30, dir=d)

    async def _drain_stderr(self, proc: asyncio.subprocess.Process) -> None:
        stream = proc.stderr
        if stream is None:
            return
        try:
            while True:
                line = await stream.readline()
                if not line:
                    return
                self._stderr_tail.append(line.decode("utf-8", errors="replace").rstrip())
                del self._stderr_tail[:-50]
        except asyncio.CancelledError:
            raise
        except Exception:
            return

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
            return await self._request_locked(op, timeout, **fields)

    async def _request_locked(self, op: str, timeout: float, **fields) -> dict:
        # Caller holds self._lock and has already ensured the process is up.
        assert self._proc is not None and self._proc.stdin and self._proc.stdout
        req_id = uuid.uuid4().hex[:8]
        payload = {"id": req_id, "op": op, "timeout_ms": int(timeout * 1000), **fields}
        self._proc.stdin.write((json.dumps(payload) + "\n").encode())
        await self._proc.stdin.drain()
        deadline = asyncio.get_running_loop().time() + timeout + 15
        # Read until the frame matching this request id. The server routes stray
        # plugin output into the eval log instead of stdout, but a plugin-spawned
        # child inheriting fd 1 could still emit a line — skip anything
        # unrecognized rather than desyncing the protocol.
        timed_out = {
            "ok": False,
            "error": f"node_repl unresponsive after {timeout}s; process restarted.",
        }
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                await self.stop()
                return timed_out
            try:
                line = await asyncio.wait_for(
                    self._proc.stdout.readline(), timeout=remaining
                )
            except asyncio.TimeoutError:
                await self.stop()
                return timed_out
            if not line:
                tail = "\n".join(self._stderr_tail[-20:])
                await self.stop()
                return {
                    "ok": False,
                    "error": "node_repl process exited unexpectedly."
                    + (f"\nstderr:\n{tail}" if tail else ""),
                }
            try:
                res = json.loads(line.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            if isinstance(res, dict) and res.get("id") == req_id:
                return res

    async def stop(self) -> None:
        proc = self._proc
        self._proc = None
        task = self._stderr_task
        self._stderr_task = None
        if task is not None:
            task.cancel()
        if proc is None or proc.returncode is not None:
            return
        # POSIX: signal the whole process group (start_new_session=True gives the
        # child its own group, so plugin-spawned children die too). Windows has no
        # killpg; fall back to terminate/kill on the process itself.
        def _signal_group(sig: int) -> None:
            killpg = getattr(os, "killpg", None)
            getpgid = getattr(os, "getpgid", None)
            if killpg is None or getpgid is None:
                raise ProcessLookupError
            killpg(getpgid(proc.pid), sig)

        try:
            _signal_group(signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            # Windows ignores start_new_session, so proc.terminate() leaves any
            # plugin-spawned children (browser hosts, playwright) orphaned. Walk
            # the tree with taskkill instead; fall back if it's unavailable.
            if os.name == "nt" and await self._taskkill_tree(proc.pid):
                await proc.wait()
                return
            try:
                proc.terminate()
            except ProcessLookupError:
                return
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            try:
                _signal_group(getattr(signal, "SIGKILL", signal.SIGTERM))
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    return
            await proc.wait()

    @staticmethod
    async def _taskkill_tree(pid: int) -> bool:
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/T", "/F", "/PID", str(pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except (FileNotFoundError, NotImplementedError, OSError):
            return False
        try:
            await asyncio.wait_for(killer.wait(), timeout=10)
        except asyncio.TimeoutError:
            return False
        return killer.returncode == 0


class NodeReplRegistry:
    """session_id -> NodeReplSession. In-memory singleton, mirroring
    AdapterRegistry: does not survive a backend restart."""

    def __init__(self) -> None:
        self._sessions: dict[str, NodeReplSession] = {}

    def get_or_create(self, key: str, working_dir: str | None) -> NodeReplSession:
        sess = self._sessions.get(key)
        if sess is None:
            sess = NodeReplSession(working_dir, key)
            self._sessions[key] = sess
        return sess

    async def close(self, key: str) -> None:
        sess = self._sessions.pop(key, None)
        if sess is not None:
            await sess.stop()


_registry = NodeReplRegistry()


def get_node_repl_registry() -> NodeReplRegistry:
    return _registry
