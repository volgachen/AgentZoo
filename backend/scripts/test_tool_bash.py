"""Test the bash tool's branches without running the backend.

Calls BashTool.execute() directly to verify each behavior path:
  - normal completion (exit code + output)
  - timeout (command killed, [Timed out] message)
  - truncation (output > max_output_length saved to a log file, [Truncated])
  - background (detached run, returns pid + log path immediately)

No uvicorn, no model, no network needed.
"""
import asyncio
import os
import sys

import _common  # noqa: F401 — sets sys.path so `app.*` imports resolve

import app.adapters.tools  # noqa: F401 — triggers @register_tool side effects
from app.adapters.tools.registry import load_tools
from _common import ok, fail, info, section


async def main() -> int:
    section("bash tool branches")
    (tool,) = load_tools(["bash"])
    failures = 0

    # 1. Normal completion
    info("--- normal completion ---")
    result = await tool.execute(command="echo hello from bash")
    if "exit code: 0" in result and "hello from bash" in result:
        ok("normal: exit code + output present")
    else:
        fail(f"normal: unexpected result: {result!r}")
        failures += 1

    # 2. Timeout — sleep longer than the timeout, expect a kill
    info("--- timeout ---")
    result = await tool.execute(command="sleep 5", timeout=1)
    if "Timed out" in result:
        ok("timeout: command terminated after limit")
    else:
        fail(f"timeout: expected [Timed out], got: {result!r}")
        failures += 1

    # 3. Truncation — emit more than max_output_length chars.
    # Go through python so the command is shell-agnostic (cmd.exe vs bash).
    info("--- truncation ---")
    result = await tool.execute(
        command="python -c \"print('x' * 5000)\"",
        max_output_length=200,
    )
    if "[Truncated]" in result and "Full log saved to:" in result:
        path = result.split("Full log saved to:")[-1].strip()
        if os.path.isfile(path):
            ok(f"truncation: inline capped, full log at {path}")
        else:
            fail(f"truncation: log path missing on disk: {path}")
            failures += 1
    else:
        fail(f"truncation: expected [Truncated], got: {result[:200]!r}")
        failures += 1

    # 4. Background — should return immediately with pid + log path
    info("--- background ---")
    result = await tool.execute(command="sleep 2", run_in_background=True)
    if "Running in background" in result and "pid=" in result:
        ok("background: returned immediately with pid + log path")
    else:
        fail(f"background: unexpected result: {result!r}")
        failures += 1

    if failures:
        print(f"\n{failures} bash branch(es) failed.")
        return 1
    print("\nAll bash branches behaved as expected.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
