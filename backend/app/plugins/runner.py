import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db.interface import IAgentDatabase
from app.models.domain import PluginStatus
from app.plugins.log_buffer import LogBuffer, LogLine


logger = logging.getLogger("agentzoo.plugin")

# backend/app/plugins/runner.py -> app/plugins -> app -> backend
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_PLUGIN_SOURCES_DIR = _BACKEND_DIR / ".plugins"


class PluginRunner:
    """Owns the lifecycle of a single plugin's python subprocess."""

    def __init__(self, plugin_id: str, db: IAgentDatabase) -> None:
        self.plugin_id = plugin_id
        self._db = db
        self._proc: asyncio.subprocess.Process | None = None
        self._buffer = LogBuffer()
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()
        self._wait_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._status: PluginStatus = PluginStatus.STOPPED
        self._last_error: str | None = None

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    @property
    def status(self) -> PluginStatus:
        return self._status

    @property
    def is_running(self) -> bool:
        return self._status == PluginStatus.RUNNING

    async def start(self, code: str) -> None:
        async with self._lock:
            if self.is_running:
                raise RuntimeError("plugin is already running")

            _PLUGIN_SOURCES_DIR.mkdir(parents=True, exist_ok=True)
            source_path = _PLUGIN_SOURCES_DIR / f"{self.plugin_id}.py"
            source_path.write_text(code, encoding="utf-8")

            self._stopping = False
            self._last_error = None
            await self._record_system(f"── start @ {datetime.now(timezone.utc).isoformat()} ──")

            try:
                # -u: unbuffered stdout so prints stream in real time.
                # start_new_session: own process group, so stop() can take the whole tree.
                self._proc = await asyncio.create_subprocess_exec(
                    sys.executable, "-u", str(source_path),
                    cwd=str(_BACKEND_DIR),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                )
            except OSError as e:
                self._last_error = f"failed to spawn: {e}"
                await self._record_system(self._last_error)
                self._status = PluginStatus.ERRORED
                await self._db.set_plugin_status(
                    self.plugin_id, PluginStatus.ERRORED, error=self._last_error,
                )
                await self._broadcast_status()
                return

            self._status = PluginStatus.RUNNING
            await self._db.set_plugin_status(self.plugin_id, PluginStatus.RUNNING)
            await self._broadcast_status()

            self._wait_task = asyncio.create_task(self._supervise())

    async def stop(self) -> None:
        async with self._lock:
            if not self.is_running or self._proc is None:
                return
            self._stopping = True
            pid = self._proc.pid
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            wait_task = self._wait_task

        if wait_task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(wait_task), timeout=3.0)
        except asyncio.TimeoutError:
            if self._proc is not None:
                try:
                    os.killpg(self._proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            await wait_task

    # ------------------------------------------------------------------
    # Subscription (WS endpoint uses these)
    # ------------------------------------------------------------------

    async def subscribe(self) -> tuple[asyncio.Queue[dict[str, Any]], list[LogLine], PluginStatus]:
        """Attach a subscriber. Returns (queue, log snapshot, current status).

        The caller should first send the snapshot + status frames, then drain the
        queue for live updates.
        """
        async with self._lock:
            q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            self._subscribers.add(q)
            return q, self._buffer.snapshot(), self._status

    def snapshot_logs(self) -> list[LogLine]:
        return self._buffer.snapshot()

    async def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._subscribers.discard(q)

    async def clear_logs(self) -> None:
        async with self._lock:
            self._buffer.clear()
        await self._broadcast({"type": "logs_cleared", "data": None})

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _supervise(self) -> None:
        assert self._proc is not None
        proc = self._proc
        readers = []
        if proc.stdout is not None:
            readers.append(self._pump(proc.stdout, "stdout"))
        if proc.stderr is not None:
            readers.append(self._pump(proc.stderr, "stderr"))

        await asyncio.gather(*readers)
        rc = await proc.wait()

        if self._stopping:
            final = PluginStatus.STOPPED
            err = None
        elif rc == 0:
            final = PluginStatus.EXITED
            err = None
        else:
            final = PluginStatus.ERRORED
            tail = [ln.line for ln in self._buffer.snapshot() if ln.stream == "stderr"][-5:]
            err = "\n".join(tail) if tail else f"exited with code {rc}"

        async with self._lock:
            self._status = final
            self._last_error = err
            self._proc = None

        await self._record_system(f"── exited rc={rc} status={final.value} ──")
        await self._db.set_plugin_status(
            self.plugin_id, final, exit_code=rc, error=err,
        )
        await self._broadcast_status()

    async def _pump(self, stream: asyncio.StreamReader, name: str) -> None:
        while True:
            try:
                line_bytes = await stream.readline()
            except Exception as e:
                logger.exception("plugin=%s pump %s read failed", self.plugin_id, name)
                await self._record_system(f"pump error: {e}")
                return
            if not line_bytes:
                return
            line = line_bytes.decode("utf-8", errors="replace").rstrip("\n")
            entry = self._buffer.append(name, line)  # type: ignore[arg-type]
            await self._broadcast({"type": "log", "data": entry.model_dump(mode="json")})

    async def _record_system(self, message: str) -> None:
        entry = self._buffer.append("system", message)
        await self._broadcast({"type": "log", "data": entry.model_dump(mode="json")})

    async def _broadcast(self, frame: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(frame)
            except asyncio.QueueFull:
                pass

    async def _broadcast_status(self) -> None:
        await self._broadcast({
            "type": "status",
            "data": {
                "status": self._status.value,
                "error": self._last_error,
            },
        })
