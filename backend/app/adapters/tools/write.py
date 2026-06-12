import os
from app.adapters.tools.base import BaseTool
from app.adapters.tools.registry import register_tool


@register_tool
class WriteTool(BaseTool):
    name = "write"
    description = (
        "Write a file to the filesystem, creating it or overwriting it entirely. "
        "Creates parent directories as needed. For modifying part of an existing "
        "file, prefer the edit tool."
    )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path of the file to write.",
                },
                "content": {
                    "type": "string",
                    "description": "The full content to write to the file.",
                },
            },
            "required": ["file_path", "content"],
        }

    async def execute(self, file_path: str, content: str) -> str:
        file_path = self.resolve_path(file_path)
        existed = os.path.isfile(file_path)
        parent = os.path.dirname(file_path)
        try:
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            return f"[Error] Could not write {file_path}: {e}"

        verb = "Updated" if existed else "Created"
        n_lines = content.count("\n") + (0 if content.endswith("\n") or not content else 1)
        return f"[{verb}] {file_path} ({n_lines} lines, {len(content)} chars)"
