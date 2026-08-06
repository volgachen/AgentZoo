import asyncio
import locale
import os
import re
import shutil
import sys
import time
import uuid
from app.adapters.tools.base import BaseTool
from app.adapters.tools.registry import register_tool

# Logs for truncated/background runs live here so the full output survives
# beyond a single ToolResult string.
_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "tmp", "bash")

_DEFAULT_TIMEOUT = 120
_DEFAULT_MAX_OUTPUT = 8192
_BASH_PATH_ENV = "AGENT_BASH_PATH"

# CWD relay: each bash call spawns a fresh subshell, so a trailing `cd` would
# normally evaporate before the next call. Like Claude Code's BashTool, we don't
# keep a persistent shell — instead we capture `pwd` to a side file after each
# command and feed it back as the cwd of the next one. The capture wrapper uses
# sh syntax (`$?`, `pwd`), so only enable it when commands run under a resolved
# bash executable. If bash cannot be resolved, we fall back to the platform's
# default shell and skip cwd relay to preserve the old behavior.


def _resolve_bash() -> str | None:
    """Resolve the Bash executable, preferring explicit configuration over PATH."""
    configured = os.environ.get(_BASH_PATH_ENV)
    if configured:
        configured_path = os.path.expandvars(os.path.expanduser(configured.strip()))
        if os.path.isfile(configured_path):
            return configured_path
        resolved_configured = shutil.which(configured_path)
        if resolved_configured:
            return resolved_configured

    return shutil.which("bash")


def _log_path() -> str:
    os.makedirs(_LOG_DIR, exist_ok=True)
    name = f"bash-{int(time.time())}-{uuid.uuid4().hex[:8]}.log"
    return os.path.abspath(os.path.join(_LOG_DIR, name))


def _cwd_file() -> str:
    os.makedirs(_LOG_DIR, exist_ok=True)
    name = f"cwd-{int(time.time())}-{uuid.uuid4().hex[:8]}.txt"
    return os.path.abspath(os.path.join(_LOG_DIR, name))


def _windows_slash_path(path: str) -> str:
    """Normalize a Windows path to drive-slash form, e.g. E:/repo."""
    if os.name != "nt":
        return path
    return os.path.abspath(path).replace("\\", "/")


def _bash_to_windows_slash_path(path: str) -> str:
    """Convert Git Bash path output to Windows drive-slash form."""
    if os.name != "nt":
        return path
    normalized = path.replace("\\", "/")
    drive_slash = re.match(r"^([A-Za-z]):/(.*)$", normalized)
    if drive_slash:
        drive, remainder = drive_slash.groups()
        return f"{drive.upper()}:/{remainder}"
    msys_root = re.match(r"^/([A-Za-z])(?:/(.*))?$", normalized)
    if msys_root:
        drive, remainder = msys_root.groups()
        return f"{drive.upper()}:/{remainder or ''}"
    return _windows_slash_path(path)


def _wrap_with_cwd_capture(command: str, cwd_file: str) -> str:
    """Append a `pwd -P` capture using a shell-native path for the side file.

    This does not disturb the command's stdout or exit code.

    The original exit code is saved before `pwd` runs and re-raised via `exit`,
    so the `[exit code: N]` header still reflects the user's command. `pwd` writes
    to its own file (not stdout), so the returned output is unchanged.
    """
    shell_cwd_file = _windows_slash_path(cwd_file)
    quoted = shell_cwd_file.replace('"', '\\"')
    return (
        f"{command}\n"
        f"__az_rc=$?\n"
        f'pwd -P > "{quoted}" 2>/dev/null || true\n'
        f"exit $__az_rc\n"
    )


def _read_cwd_file(cwd_file: str) -> str | None:
    """Read back the captured cwd, validate it's a real directory, and clean up.

    Best-effort: a missing/empty/stale value just leaves the cwd unchanged.
    """
    try:
        with open(cwd_file, encoding="utf-8") as f:
            value = f.read().strip()
    except OSError:
        return None
    finally:
        try:
            os.remove(cwd_file)
        except OSError:
            pass
    value = _bash_to_windows_slash_path(value)
    if value and os.path.isdir(value):
        return value
    return None


def _decode_process_output(data: bytes) -> str:
    """Decode subprocess output without corrupting non-UTF-8 Windows output.

    UTF-8 is still preferred because most tools emit it. On Windows, however,
    commands launched through the default shell often emit the active ANSI/OEM
    code page, such as cp936 for Simplified Chinese. Decoding those bytes with
    errors="replace" produces permanent replacement characters like "����".
    """
    encodings = [
        "utf-8",
        locale.getpreferredencoding(False),
        sys.getfilesystemencoding(),
    ]
    if os.name == "nt":
        encodings.extend(["mbcs", "oem", "cp936", "gb18030"])

    tried: set[str] = set()
    for encoding in encodings:
        if not encoding:
            continue
        normalized = encoding.lower()
        if normalized in tried:
            continue
        tried.add(normalized)
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue

    return data.decode("utf-8", errors="replace")


@register_tool
class BashTool(BaseTool):
    name = "bash"
    # Relayed working directory: advances when a command ends with a `cd`, so the
    # next bash call resumes where the previous one left off. Initialized lazily
    # from working_dir on first use. Persists for the lifetime of the tool
    # instance (one per session), so it does not survive a backend restart — the
    # session's static working_dir is the fallback.
    _cwd: str | None = None
    _bash_path: str | None = None
    _bash_resolved: bool = False
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

    def _effective_cwd(self) -> str | None:
        """Where the next command runs: the relayed cwd if a prior `cd` advanced
        it, else the session's static working_dir."""
        return self._cwd or self.working_dir

    def _get_bash_path(self) -> str | None:
        if not self._bash_resolved:
            self._bash_path = _resolve_bash()
            self._bash_resolved = True
        return self._bash_path

    def _bash_command_args(self, command: str) -> list[str] | None:
        bash_path = self._get_bash_path()
        if not bash_path:
            return None
        return [bash_path, "-lc", command]

    async def _run_background(self, command: str) -> str:
        path = _log_path()
        # Keep the file handle open for the lifetime of the child; the OS closes
        # it when the detached process exits.
        log_file = open(path, "wb")
        bash_args = self._bash_command_args(command)
        if bash_args:
            proc = await asyncio.create_subprocess_exec(
                *bash_args,
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
                cwd=self._effective_cwd(),
            )
        else:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
                cwd=self._effective_cwd(),
            )
        return (
            f"[Running in background] pid={proc.pid}\n"
            f"Output is being written to: {path}"
        )

    async def _run_foreground(
        self, command: str, timeout: int, max_output_length: int
    ) -> str:
        # CWD relay: wrap the command so it records its final directory to a side
        # file, then read it back to advance self._cwd for the next call. This is
        # only safe when running under bash; fallback shells keep the old static cwd.
        bash_args = self._bash_command_args(command)
        cwd_file = _cwd_file() if bash_args else None
        if cwd_file:
            bash_args = self._bash_command_args(_wrap_with_cwd_capture(command, cwd_file))

        if bash_args:
            proc = await asyncio.create_subprocess_exec(
                *bash_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=self._effective_cwd(),
            )
        else:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=self._effective_cwd(),
            )

        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            if cwd_file:
                _read_cwd_file(cwd_file)  # discard result, just clean up
            return (
                f"[Timed out] Command exceeded {timeout}s and was terminated:\n"
                f"$ {command}"
            )

        if cwd_file:
            new_cwd = _read_cwd_file(cwd_file)
            if new_cwd:
                self._cwd = new_cwd

        output = _decode_process_output(stdout)
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
