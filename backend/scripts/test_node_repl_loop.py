#!/usr/bin/env python3
"""Verify the full node_repl loop driven ONLY through the three repl tools.

Unlike test_node_repl.py (interactive), this is a standalone assertion script:
it exercises node_repl_js / node_repl_reset / node_repl_add_module_dir exactly
as the OpenAI tool-use adapter would (via each tool's .execute()), asserts the
observable behavior, and exits 0 on success / 1 on failure.

What it proves:
  - the three tools share ONE persistent Node subprocess per session_id
  - globalThis state persists across separate node_repl_js calls
  - top-level await works
  - node_repl_add_module_dir makes a plugin's node_modules resolvable
  - node_repl_reset clears user globals but keeps the process alive
  - aclose() tears the subprocess down

Run from backend/:  python scripts/test_node_repl_loop.py
No live gateway, DB, or OPENAI_* needed — only a Node runtime (NODE_BIN or PATH).
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.adapters.tools.node_repl import (  # noqa: E402
    NodeReplJsTool,
    NodeReplResetTool,
    NodeReplAddModuleDirTool,
)

_PASS = 0
_FAIL = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    mark = "PASS" if cond else "FAIL"
    if cond:
        _PASS += 1
    else:
        _FAIL += 1
    line = f"  [{mark}] {label}"
    if detail and not cond:
        line += f"\n         -> {detail}"
    print(line)


def _plugin_scripts_dir() -> str | None:
    """Best-effort locate a bundled codex plugin's scripts/ dir for the
    add_module_dir + import leg. Skipped gracefully if the plugins aren't here."""
    root = os.path.join(os.path.dirname(__file__), "..", "..", "codex_plugins")
    for plugin in ("chrome", "browser"):
        base = os.path.join(root, plugin)
        if not os.path.isdir(base):
            continue
        for ver in sorted(os.listdir(base), reverse=True):
            scripts = os.path.join(base, ver, "scripts")
            if os.path.isfile(os.path.join(scripts, "browser-client.mjs")):
                return os.path.abspath(scripts)
    return None


async def main() -> int:
    # All three tools share one session_id -> one subprocess (as the adapter wires
    # them). This is the whole point: the loop is controlled purely by the tools.
    sid = "loop-verify"
    js = NodeReplJsTool()
    reset = NodeReplResetTool()
    add = NodeReplAddModuleDirTool()
    for t in (js, reset, add):
        t.session_id = sid

    print("node_repl loop verification (driven only via the three tools)\n")

    # 1. basic eval + console.log capture + return value
    out = await js.execute(code='console.log("hello"); return 2 + 3;')
    print(out)
    check("node_repl_js: console.log + return value", "hello" in out and "=> 5" in out, out)

    # 2. state persists across separate node_repl_js calls (shared globalThis)
    await js.execute(code="globalThis.counter = 40;")
    out = await js.execute(code="globalThis.counter += 2; return globalThis.counter;")
    print(out)
    check("node_repl_js: globalThis persists across calls", "=> 42" in out, out)

    print("  3. top-level await ")
    out = await js.execute(
        code='await new Promise(r => setTimeout(r, 10)); return "awaited";'
    )
    print(out)
    check("node_repl_js: top-level await", '"awaited"' in out, out)

    print("  4. error surfaces without killing the session ")
    out = await js.execute(code='throw new Error("boom");')
    print(out)
    check("node_repl_js: error is reported", "boom" in out and "[error]" in out, out)
    out = await js.execute(code="return globalThis.counter;")
    print(out)
    check("node_repl_js: session survives an error", "=> 42" in out, out)

    print("  5. add_module_dir + import a real plugin entry (skipped if plugins absent) ")
    scripts_dir = _plugin_scripts_dir()
    if scripts_dir:
        node_modules = os.path.join(scripts_dir, "node_modules")
        out = await add.execute(dir=node_modules)
        print(out)
        check("node_repl_add_module_dir: accepted", "added" in out, out)
        entry = os.path.join(scripts_dir, "browser-client.mjs").replace("\\", "\\\\")
        out = await js.execute(
            code=f'const m = await import("{entry}"); return Object.keys(m);'
        )
        print(out)
        check(
            "node_repl_js: plugin browser-client.mjs imports",
            "setupBrowserRuntime" in out,
            out,
        )
    else:
        print("  [SKIP] plugin import leg (codex_plugins/ not found)")

    print(" 6. reset clears user globals but keeps the process (and its identity) alive ")
    out = await reset.execute()
    print(out)
    check("node_repl_reset: returns ok", "reset" in out, out)
    out = await js.execute(code="return typeof globalThis.counter;")
    print(out)
    check("node_repl_reset: user globals cleared", '"undefined"' in out, out)
    out = await js.execute(code='return "still-alive";')
    print(out)
    check("node_repl_reset: process still usable after reset", "still-alive" in out, out)

    print(" 7. teardown ")
    await js.aclose()
    out = await js.execute(code='return "respawned";')
    check("aclose then reuse: subprocess respawns cleanly", "respawned" in out, out)
    await js.aclose()

    print(f"\n{_PASS} passed, {_FAIL} failed")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
