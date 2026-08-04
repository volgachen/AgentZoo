from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
import fnmatch

PermissionAction = Literal["allow", "deny", "ask"]

_FILE_PATH_ARG_BY_TOOL = {
    "read": "path",
    "write": "file_path",
    "edit": "file_path",
}


@dataclass(frozen=True)
class ToolPermissionDecision:
    action: PermissionAction
    reason: str
    rule_id: str | None = None


def decide_tool_permission(
    tool_name: str,
    tool_args: dict[str, Any],
    working_dir: str | None,
    config: dict[str, Any] | None,
) -> ToolPermissionDecision | None:
    """Return a policy decision for configured tool permissions.

    This first implementation intentionally handles only filesystem tools
    (read/write/edit). Returning None means "no new-style policy applies" so the
    caller should fall back to the legacy requires_approval/tool_approvals flow.
    """
    permissions = (config or {}).get("tool_permissions")
    if not isinstance(permissions, dict):
        return None

    path_arg = _FILE_PATH_ARG_BY_TOOL.get(tool_name)
    if path_arg is None:
        return None

    raw_path = tool_args.get(path_arg)
    if not isinstance(raw_path, str) or not raw_path:
        return ToolPermissionDecision("ask", f"missing or invalid path argument '{path_arg}'")

    try:
        resolved_path = _resolve_tool_path(raw_path, working_dir)
    except OSError as e:
        return ToolPermissionDecision("ask", f"could not resolve path: {e}")

    rules = permissions.get("rules", [])
    matching_allow: ToolPermissionDecision | None = None
    if isinstance(rules, list):
        for index, rule in enumerate(rules):
            if not isinstance(rule, dict):
                continue
            if not _tool_matches(rule, tool_name):
                continue
            paths = rule.get("paths")
            if not isinstance(paths, list):
                continue
            if not _path_matches_any(resolved_path, paths, working_dir):
                continue

            effect = rule.get("effect")
            rule_id = rule.get("id") if isinstance(rule.get("id"), str) else None
            label = rule_id or f"rule_index={index}"
            if effect == "deny":
                return ToolPermissionDecision("deny", f"matched deny rule {label}", rule_id)
            if effect == "allow" and matching_allow is None:
                matching_allow = ToolPermissionDecision("allow", f"matched allow rule {label}", rule_id)

    if matching_allow is not None:
        return matching_allow

    default = permissions.get("default", "ask")
    if default in ("allow", "deny", "ask"):
        return ToolPermissionDecision(default, "no matching rule; using tool_permissions.default")
    return ToolPermissionDecision("ask", "invalid tool_permissions.default; using ask")


def _tool_matches(rule: dict[str, Any], tool_name: str) -> bool:
    rule_tool = rule.get("tool")
    rule_tools = rule.get("tools")
    if rule_tool == "*" or rule_tool == tool_name:
        return True
    if isinstance(rule_tools, list):
        return "*" in rule_tools or tool_name in rule_tools
    return False


def _resolve_tool_path(path: str, working_dir: str | None) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute() and working_dir:
        p = Path(working_dir).expanduser() / p
    return p.resolve(strict=False)


def _path_matches_any(path: Path, patterns: list[Any], working_dir: str | None) -> bool:
    return any(
        isinstance(pattern, str) and _path_matches(path, pattern, working_dir)
        for pattern in patterns
    )


def _path_matches(path: Path, pattern: str, working_dir: str | None) -> bool:
    # Treat relative patterns as workspace-relative when a working_dir exists.
    # Absolute tool-call paths are still normalized before matching, so ../ cannot
    # escape a narrower allow pattern such as ./docs/**.
    pattern_path = Path(pattern).expanduser()
    if pattern_path.is_absolute() or working_dir:
        if not pattern_path.is_absolute():
            pattern_path = Path(working_dir or ".").expanduser() / pattern_path
        normalized_pattern = _normalize_glob_pattern(pattern_path)
        return fnmatch.fnmatch(str(path), normalized_pattern)

    # Legacy no-working-dir case: match normalized relative-looking strings.
    return fnmatch.fnmatch(str(path), pattern)


def _normalize_glob_pattern(path: Path) -> str:
    # Path.resolve() cannot be used directly because glob metacharacters do not
    # need to exist on disk and should not be treated as literal path components.
    parts: list[str] = []
    for part in path.parts:
        if any(ch in part for ch in "*?["):
            parts.append(part)
        else:
            if not parts:
                parts.append(part)
            else:
                current = Path(*parts, part)
                parts = list(current.resolve(strict=False).parts)
    return str(Path(*parts))
