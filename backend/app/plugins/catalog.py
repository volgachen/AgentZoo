import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError


logger = logging.getLogger("augentia.plugin_catalog")

PluginScope = Literal["system_side", "session_side", "hybrid"]


class PluginEntry(BaseModel):
    type: str
    main: str | None = None
    skill: str | None = None
    scripts_dir: str | None = None


class PluginSessionSpec(BaseModel):
    selectable: bool = False
    default_enabled: bool = False


class PluginDefinition(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    version: str = "0.0.0"
    scope: PluginScope = "system_side"
    provider: str = "augentia"
    description: str = ""
    entry: PluginEntry
    capabilities: list[str] = Field(default_factory=list)
    subscriptions: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    default_config: dict[str, Any] = Field(default_factory=dict)
    session: PluginSessionSpec = Field(default_factory=PluginSessionSpec)
    root: str


class PluginCatalog:
    """Scans local plugin directories for plugin.json definitions.

    Installed plugin code lives outside app/plugins, which is reserved for the
    backend runtime implementation. By default we scan <backend>/plugins.
    """

    def __init__(self, plugins_dir: Path | None = None) -> None:
        backend_dir = Path(__file__).resolve().parents[2]
        self.plugins_dir = plugins_dir or (backend_dir / "plugins")

    def list(self) -> list[PluginDefinition]:
        definitions: list[PluginDefinition] = []
        if not self.plugins_dir.exists():
            return definitions
        for manifest in sorted(self.plugins_dir.glob("*/plugin.json")):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                data["root"] = str(manifest.parent)
                definitions.append(PluginDefinition.model_validate(data))
            except (OSError, json.JSONDecodeError, ValidationError) as e:
                logger.warning("skipping invalid plugin manifest %s: %s", manifest, e)
        return definitions

    def get(self, plugin_id: str) -> PluginDefinition:
        for definition in self.list():
            if definition.id == plugin_id:
                return definition
        raise KeyError(f"Plugin definition '{plugin_id}' not found")


def get_plugin_catalog() -> PluginCatalog:
    return PluginCatalog()
