#!/usr/bin/env python3
"""Interactive CLI for testing/debugging the node_repl tool family.

Usage:
    python scripts/test_node_repl.py
    python scripts/test_node_repl.py --working-dir /path/to/dir

Commands:
    .eval <code>           Execute JavaScript (default if no command prefix)
    .reset                 Clear globalThis state
    .add <dir>             Add directory to module resolution paths
    .help                  Show this help
    .quit / .exit / ^D     Exit

Examples:
    > globalThis.x = 42; console.log("hi"); return x + 1;
    > .eval await new Promise(r => setTimeout(r, 100)); return "done";
    > .add /home/user/projects/AgentZoo/codex_plugins/chrome/26.715.72359/scripts
    > .eval const m = await import("/path/to/plugin/scripts/browser-client.mjs"); return Object.keys(m);
    > .reset
"""
import asyncio
import argparse
import sys
import os

# Add backend to path so we can import app modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.adapters.tools.node_repl import (
    NodeReplJsTool,
    NodeReplResetTool,
    NodeReplAddModuleDirTool,
)


class ReplCli:
    def __init__(self, working_dir: str | None):
        self.js = NodeReplJsTool()
        self.reset_tool = NodeReplResetTool()
        self.add_tool = NodeReplAddModuleDirTool()

        # Share session_id so they all use the same subprocess
        session_id = "cli-repl"
        self.js.session_id = session_id
        self.reset_tool.session_id = session_id
        self.add_tool.session_id = session_id

        if working_dir:
            self.js.working_dir = working_dir
            self.reset_tool.working_dir = working_dir
            self.add_tool.working_dir = working_dir

    async def run(self):
        print(__doc__)
        print(f"Node REPL session started (session_id: {self.js.session_id})")
        if self.js.working_dir:
            print(f"Working directory: {self.js.working_dir}")
        print()

        while True:
            try:
                # Read input
                line = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input("> ")
                )
                line = line.strip()

                if not line:
                    continue

                # Parse command
                if line.startswith("."):
                    parts = line.split(maxsplit=1)
                    cmd = parts[0]
                    arg = parts[1] if len(parts) > 1 else ""

                    if cmd in (".quit", ".exit"):
                        break
                    elif cmd == ".help":
                        print(__doc__)
                        continue
                    elif cmd == ".reset":
                        result = await self.reset_tool.execute()
                        print(result)
                        continue
                    elif cmd == ".add":
                        if not arg:
                            print("Usage: .add <directory>")
                            continue
                        result = await self.add_tool.execute(dir=arg)
                        print(result)
                        continue
                    elif cmd == ".eval":
                        if not arg:
                            print("Usage: .eval <code>")
                            continue
                        code = arg
                    else:
                        print(f"Unknown command: {cmd}")
                        print("Type .help for available commands")
                        continue
                else:
                    # No command prefix, treat as eval
                    code = line

                # Execute
                result = await self.js.execute(code=code)
                print(result)

            except EOFError:
                break
            except KeyboardInterrupt:
                print("\n(interrupted, type .quit to exit)")
                continue
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc()

        # Cleanup
        print("\nShutting down...")
        await self.js.aclose()
        print("Goodbye!")


async def main():
    parser = argparse.ArgumentParser(
        description="Interactive CLI for node_repl tool debugging"
    )
    parser.add_argument(
        "--working-dir",
        "-w",
        default=None,
        help="Working directory for the Node subprocess",
    )
    args = parser.parse_args()

    cli = ReplCli(working_dir=args.working_dir)
    await cli.run()


if __name__ == "__main__":
    asyncio.run(main())
