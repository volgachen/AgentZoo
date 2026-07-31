import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db.interface import IAgentDatabase
from app.models.domain import PluginInstance, PluginRun, PluginStatus
from app.plugins.actions import PluginActionDispatcher
from app.plugins.catalog import PluginDefinition
from app.plugins.events import PluginEvent
from app.plugins.log_buffer import LogBuffer, LogLine


logger = logging.getLogger("augentia.plugin")

_BACKEND_DIR = Path(__file__).resolve().parents[2]


class PluginRunner:
    """Owns the lifecycle of one plugin instance's current run."""

    def __init__(
        self,
        instance_id: str,
        db: IAgentDatabase,
        action_dispatcher: PluginActionDispatcher | None = None,
    ) -> None:
        self.instance_id = instance_id
        self._db = db
        self._action_dispatcher = action_dispatcher
        self._proc: asyncio.subprocess.Process | None = None
        self._buffer = LogBuffer()
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()
        self._wait_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._status: PluginStatus = PluginStatus.STOPPED
        self._last_error: str | None = None
        self._run_id: str | None = None

    def set_action_dispatcher(self, action_dispatcher: PluginActionDispatcher | None) -> None:
        if action_dispatcher is not None:
            self._action_dispatcher = action_dispatcher

    @property
    def status(self) -> PluginStatus:
        return self._status

    @property
    def is_running(self) -> bool:
        return self._status in {
            PluginStatus.STARTING,
            PluginStatus.WAITING_INPUT,
            PluginStatus.RUNNING,
            PluginStatus.STOPPING,
        }

    @property
    def run_id(self) -> str | None:
        return self._run_id

    async def start(
        self,
        definition: PluginDefinition,
        instance: PluginInstance,
    ) -> PluginRun:
        async with self._lock:
            if self.is_running:
                raise RuntimeError("plugin instance is already running")
            if definition.entry.type != "python":
                raise RuntimeError(
                    f"plugin entry type '{definition.entry.type}' is not runnable as a background process yet"
                )
            if not definition.entry.main:
                raise RuntimeError("python plugin entry requires entry.main")

            source_path = (Path(definition.root) / definition.entry.main).resolve()
            root = Path(definition.root).resolve()
            if not source_path.is_file():
                raise RuntimeError(f"plugin entry file not found: {source_path}")
            if root not in source_path.parents and source_path != root:
                raise RuntimeError("plugin entry must be inside plugin root")

            self._buffer.clear()
            self._stopping = False
            self._last_error = None
            self._status = PluginStatus.STARTING

            run = await self._db.create_plugin_run(
                instance.id,
                instance.plugin_id,
                config_snapshot=instance.config,
            )
            self._run_id = run.id
            await self._db.update_plugin_instance(
                instance.id,
                status=PluginStatus.STARTING,
                current_run_id=run.id,
            )
            await self._record_system(f"── start @ {datetime.now(timezone.utc).isoformat()} ──")
            await self._broadcast_status()

            try:
                env = os.environ.copy()
                env.update({
                    "AUGENTIA_PLUGIN_ID": definition.id,
                    "AUGENTIA_PLUGIN_INSTANCE_ID": instance.id,
                    "AUGENTIA_PLUGIN_RUN_ID": run.id,
                    "AUGENTIA_PLUGIN_ROOT": str(root),
                    "AUGENTIA_PLUGIN_CONFIG": json.dumps(instance.config or {}, ensure_ascii=False),
                })
                self._proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-u",
                    str(source_path),
                    cwd=str(root),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                    env=env,
                )
            except OSError as e:
                self._last_error = f"failed to spawn: {e}"
                self._status = PluginStatus.ERRORED
                now = datetime.now(timezone.utc)
                await self._record_system(self._last_error)
                await self._db.update_plugin_run(
                    run.id,
                    status=PluginStatus.ERRORED,
                    exited_at=now,
                    error=self._last_error,
                )
                await self._db.update_plugin_instance(instance.id, status=PluginStatus.ERRORED)
                await self._broadcast_status()
                return await self._db.get_plugin_run(run.id)

            self._status = PluginStatus.RUNNING
            now = datetime.now(timezone.utc)
            await self._db.update_plugin_run(
                run.id,
                status=PluginStatus.RUNNING,
                running_at=now,
            )
            await self._db.update_plugin_instance(instance.id, status=PluginStatus.RUNNING)
            await self._broadcast_status()

            self._wait_task = asyncio.create_task(self._supervise(instance.id, run.id))
            return await self._db.get_plugin_run(run.id)

    async def stop(self) -> None:
        async with self._lock:
            if not self.is_running or self._proc is None:
                return
            self._stopping = True
            self._status = PluginStatus.STOPPING
            run_id = self._run_id
            if run_id is not None:
                await self._db.update_plugin_run(run_id, status=PluginStatus.STOPPING)
            await self._db.update_plugin_instance(self.instance_id, status=PluginStatus.STOPPING)
            await self._broadcast_status()
            proc = self._proc
            pid = proc.pid
            try:
                if hasattr(os, "killpg"):
                    os.killpg(pid, signal.SIGTERM)
                else:
                    proc.terminate()
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
                    if hasattr(os, "killpg"):
                        os.killpg(self._proc.pid, signal.SIGKILL)
                    else:
                        self._proc.kill()
                except ProcessLookupError:
                    pass
            await wait_task

    async def subscribe(self) -> tuple[asyncio.Queue[dict[str, Any]], list[LogLine], PluginStatus]:
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

    async def send_event(self, event: PluginEvent) -> None:
        async with self._lock:
            proc = self._proc
            if proc is None or proc.stdin is None or not self.is_running:
                return
            frame = {
                "type": "event",
                "event": event.model_dump(mode="json"),
            }
            try:
                proc.stdin.write((json.dumps(frame, ensure_ascii=False) + "\n").encode("utf-8"))
                await proc.stdin.drain()
            except Exception as e:
                logger.exception("failed to send plugin event instance=%s", self.instance_id)
                await self._record_system(f"event delivery failed: {event.type}: {e}")

    async def _supervise(self, instance_id: str, run_id: str) -> None:
        assert self._proc is not None
        proc = self._proc
        readers = []
        if proc.stdout is not None:
            readers.append(self._pump(proc.stdout, "stdout", instance_id, run_id))
        if proc.stderr is not None:
            readers.append(self._pump(proc.stderr, "stderr", instance_id, run_id))

        await asyncio.gather(*readers)
        rc = await proc.wait()

        if self._stopping:
            final = PluginStatus.EXITED
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
        now = datetime.now(timezone.utc)
        await self._db.update_plugin_run(
            run_id,
            status=final,
            exited_at=now,
            exit_code=rc,
            error=err,
        )
        await self._db.update_plugin_instance(instance_id, status=final)
        await self._broadcast_status()

    async def _pump(
        self,
        stream: asyncio.StreamReader,
        name: str,
        instance_id: str,
        run_id: str,
    ) -> None:
        while True:
            try:
                line_bytes = await stream.readline()
            except Exception as e:
                logger.exception("plugin_instance=%s pump %s read failed", instance_id, name)
                await self._record_system(f"pump error: {e}")
                return
            if not line_bytes:
                return
            line = line_bytes.decode("utf-8", errors="replace").rstrip("\r\n")
            entry = self._buffer.append(name, line)  # type: ignore[arg-type]
            await self._db.add_plugin_log(instance_id, run_id, name, line)
            await self._broadcast({"type": "log", "data": entry.model_dump(mode="json")})
            if name == "stdout":
                await self._maybe_dispatch_action(instance_id, run_id, line)

    async def _maybe_dispatch_action(self, instance_id: str, run_id: str, line: str) -> None:
        if self._action_dispatcher is None:
            return
        try:
            frame = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(frame, dict) or frame.get("type") != "action":
            return
        action = frame.get("action")
        data = frame.get("data") or {}
        if not isinstance(action, str) or not isinstance(data, dict):
            await self._record_system("invalid plugin action frame")
            return
        try:
            await self._action_dispatcher.dispatch(
                plugin_instance_id=instance_id,
                plugin_run_id=run_id,
                action=action,
                data=data,
            )
            await self._record_system(f"action dispatched: {action}")
        except Exception as e:
            logger.exception("plugin action failed instance=%s action=%s", instance_id, action)
            await self._record_system(f"action failed: {action}: {e}")

    async def _record_system(self, message: str) -> None:
        entry = self._buffer.append("system", message)
        if self._run_id is not None:
            await self._db.add_plugin_log(self.instance_id, self._run_id, "system", message)
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
                "run_id": self._run_id,
            },
        })
