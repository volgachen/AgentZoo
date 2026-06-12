import asyncio
import os
import time
import uuid
from app.adapters.tools.base import BaseTool
from app.adapters.tools.registry import register_tool

# Logs for truncated/background runs live here so the full output survives
# beyond a single ToolResult string.
_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "tmp", "bash")

_DEFAULT_TIMEOUT = 120
_DEFAULT_MAX_OUTPUT = 8192


def _log_path() -> str:
    os.makedirs(_LOG_DIR, exist_ok=True)
    name = f"bash-{int(time.time())}-{uuid.uuid4().hex[:8]}.log"
    return os.path.abspath(os.path.join(_LOG_DIR, name))


@register_tool
class BashTool(BaseTool):
    name = "bash"
    description = (
        "Run a shell command on the host and return its combined stdout/stderr. "
        "Use timeout to bound runtime, max_output_length to cap returned text "
        "(overflow is written to a log file), and run_in_background for "
        "long-running commands that should not block."
    )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        "Seconds to wait for completion before aborting "
                        f"(default {_DEFAULT_TIMEOUT}). Ignored when "
                        "run_in_background is true."
                    ),
                    "default": _DEFAULT_TIMEOUT,
                },
                "max_output_length": {
                    "type": "integer",
                    "description": (
                        "Max characters of output to return inline (default "
                        f"{_DEFAULT_MAX_OUTPUT}). Longer output is saved to a log "
                        "file and truncated in the result."
                    ),
                    "default": _DEFAULT_MAX_OUTPUT,
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": (
                        "If true, run detached with all output redirected to a log "
                        "file and return immediately without waiting."
                    ),
                    "default": False,
                },
            },
            "required": ["command"],
        }

    async def execute(
        self,
        command: str,
        timeout: int = _DEFAULT_TIMEOUT,
        max_output_length: int = _DEFAULT_MAX_OUTPUT,
        run_in_background: bool = False,
    ) -> str:
        if run_in_background:
            return await self._run_background(command)
        return await self._run_foreground(command, timeout, max_output_length)

    async def _run_background(self, command: str) -> str:
        path = _log_path()
        # Keep the file handle open for the lifetime of the child; the OS closes
        # it when the detached process exits.
        log_file = open(path, "wb")
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=log_file,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
            cwd=self.working_dir,
        )
        return (
            f"[Running in background] pid={proc.pid}\n"
            f"Output is being written to: {path}"
        )

    async def _run_foreground(
        self, command: str, timeout: int, max_output_length: int
    ) -> str:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=self.working_dir,
        )

        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return (
                f"[Timed out] Command exceeded {timeout}s and was terminated:\n"
                f"$ {command}"
            )

        output = stdout.decode("utf-8", errors="replace")
        header = f"[exit code: {proc.returncode}]\n"

        if len(output) <= max_output_length:
            return header + (output if output else "(no output)")

        path = _log_path()
        with open(path, "w", encoding="utf-8") as f:
            f.write(output)
        return (
            header
            + output[:max_output_length]
            + f"\n\n[Truncated] Output exceeded {max_output_length} characters "
            f"({len(output)} total). Full log saved to: {path}"
        )
