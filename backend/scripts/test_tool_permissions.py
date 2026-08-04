import tempfile
from pathlib import Path

import _common  # noqa: F401 — sets sys.path

from app.adapters.tools.permissions import decide_tool_permission


def assert_decision(action: str, tool: str, args: dict, cwd: str, config: dict) -> None:
    decision = decide_tool_permission(tool, args, cwd, config)
    assert decision is not None
    assert decision.action == action, f"expected {action}, got {decision}"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        config = {
            "tool_permissions": {
                "default": "ask",
                "rules": [
                    {
                        "id": "allow-read-all",
                        "effect": "allow",
                        "tool": "read",
                        "paths": ["./**"],
                    },
                    {
                        "id": "allow-write-edit-docs",
                        "effect": "allow",
                        "tools": ["write", "edit"],
                        "paths": ["./docs/**"],
                    },
                    {
                        "id": "deny-sensitive",
                        "effect": "deny",
                        "tool": "*",
                        "paths": ["./.env", "./secrets/**"],
                    },
                ],
            }
        }

        assert_decision("allow", "read", {"path": "src/a.py"}, str(root), config)
        assert_decision("allow", "write", {"file_path": "docs/new.md"}, str(root), config)
        assert_decision("allow", "edit", {"file_path": "docs/a.md"}, str(root), config)
        assert_decision("deny", "read", {"path": ".env"}, str(root), config)
        assert_decision("deny", "edit", {"file_path": "docs/../.env"}, str(root), config)
        assert_decision("ask", "write", {"file_path": "notes/a.md"}, str(root), config)

        bash_decision = decide_tool_permission("bash", {"command": "git status"}, str(root), config)
        assert bash_decision is None, f"bash should fall back to legacy flow, got {bash_decision}"

    print("tool permission checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
