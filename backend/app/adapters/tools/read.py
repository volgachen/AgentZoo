import os
from app.adapters.tools.base import BaseTool
from app.adapters.tools.registry import register_tool

# No tokenizer dependency in the project, so approximate tokens from characters
# (~4 chars/token is the usual rule of thumb for English/code).
_MAX_TOKENS = 16384
_CHARS_PER_TOKEN = 4
_MAX_CHARS = _MAX_TOKENS * _CHARS_PER_TOKEN


@register_tool
class ReadTool(BaseTool):
    name = "read"
    description = (
        "Read a text file and return its contents with 1-based line numbers "
        "(format: '<lineno>\\t<content>'). Use offset/limit to read a slice. "
        f"Output is truncated past ~{_MAX_TOKENS} tokens."
    )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the file to read.",
                },
                "offset": {
                    "type": "integer",
                    "description": (
                        "1-based line number to start reading from "
                        "(default: start of file)."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read (default: all).",
                },
            },
            "required": ["path"],
        }

    async def execute(
        self,
        path: str,
        offset: int | None = None,
        limit: int | None = None,
    ) -> str:
        path = self.resolve_path(path)
        if not os.path.isfile(path):
            return f"[Error] File not found: {path}"

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError as e:
            return f"[Error] Could not read {path}: {e}"

        start = (offset - 1) if offset and offset > 0 else 0
        end = (start + limit) if limit and limit > 0 else len(lines)
        selected = lines[start:end]

        rendered: list[str] = []
        chars = 0
        truncated = False
        for i, content in enumerate(selected):
            row = f"{start + i + 1}\t{content}"
            if chars + len(row) + 1 > _MAX_CHARS:
                truncated = True
                break
            rendered.append(row)
            chars += len(row) + 1

        output = "\n".join(rendered)
        if truncated:
            output += f"\n[Truncated: output exceeded {_MAX_TOKENS} tokens]"
        return output if output else "(empty file)"
