from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import get_settings

_DEFAULT_TOOL_PERMISSIONS = {
    "default": "ask",
    "rules": [
        {
            "id": "allow-read-workspace",
            "effect": "allow",
            "tool": "read",
            "paths": ["./**"],
        },
        {
            "id": "deny-sensitive-files",
            "effect": "deny",
            "tool": "*",
            "paths": ["./.env", "./.env.*", "./secrets/**", "./.git/**"],
        },
    ],
}


def session_config_dir(session_id: str) -> Path:
    return Path(get_settings().augentia_home).expanduser() / "sessions" / session_id


def session_config_path(session_id: str) -> Path:
    return session_config_dir(session_id) / "config.json"


def default_session_config(agent_config: dict[str, Any] | None = None) -> dict[str, Any]:
    config: dict[str, Any] = {"version": 1}
    tool_permissions = (agent_config or {}).get("tool_permissions")
    config["tool_permissions"] = tool_permissions or _DEFAULT_TOOL_PERMISSIONS
    return config


def ensure_session_config(
    session_id: str,
    agent_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = session_config_path(session_id)
    if path.exists():
        return read_session_config(session_id)
    config = default_session_config(agent_config)
    write_session_config(session_id, config)
    return config


def read_session_config(session_id: str) -> dict[str, Any]:
    path = session_config_path(session_id)
    try:
        with path.open("r", encoding="utf-8") as f:
            value = json.load(f)
    except FileNotFoundError:
        config = default_session_config()
        write_session_config(session_id, config)
        return config
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid session config JSON at {path}: {e}") from e
    if not isinstance(value, dict):
        raise ValueError(f"session config must be a JSON object: {path}")
    return value


def write_session_config(session_id: str, config: dict[str, Any]) -> dict[str, Any]:
    path = session_config_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)
    return config
