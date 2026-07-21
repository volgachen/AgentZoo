from typing import Type
from app.adapters.tools.base import BaseTool

_REGISTRY: dict[str, Type[BaseTool]] = {}


def register_tool(cls: Type[BaseTool]) -> Type[BaseTool]:
    _REGISTRY[cls.name] = cls
    return cls


def load_tools(names: list[str]) -> list[BaseTool]:
    missing = [n for n in names if n not in _REGISTRY]
    if missing:
        raise ValueError(f"Unknown tools: {missing}. Available: {list(_REGISTRY)}")
    return [_REGISTRY[n]() for n in names]


def list_available() -> list[str]:
    return list(_REGISTRY.keys())


def default_approvals() -> dict[str, bool]:
    """Map each registered tool name to its class-level requires_approval default.
    This is the backend-wide baseline an agent's config.tool_approvals overrides."""
    return {name: cls.requires_approval for name, cls in _REGISTRY.items()}
