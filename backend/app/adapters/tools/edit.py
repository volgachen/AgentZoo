import os
from app.adapters.tools.base import BaseTool
from app.adapters.tools.registry import register_tool


@register_tool
class EditTool(BaseTool):
    name = "edit"
    description = (
        "Replace an exact string in an existing file. old_string must match the "
        "file exactly (including whitespace/indentation) and, unless replace_all "
        "is true, must be unique — otherwise the edit is rejected so you can add "
        "more surrounding context."
    )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path of the file to modify.",
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact text to replace.",
                },
                "new_string": {
                    "type": "string",
                    "description": "The text to replace it with (must differ from old_string).",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace every occurrence instead of requiring a unique match.",
                    "default": False,
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        }

    async def execute(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> str:
        if not os.path.isfile(file_path):
            return f"[Error] File not found: {file_path}"
        if old_string == new_string:
            return "[Error] old_string and new_string are identical — nothing to change."
        if old_string == "":
            return "[Error] old_string is empty — use the write tool to create a file."

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            return f"[Error] Could not read {file_path}: {e}"

        count = content.count(old_string)
        if count == 0:
            return f"[Error] old_string not found in {file_path}."
        if count > 1 and not replace_all:
            return (
                f"[Error] old_string is not unique ({count} matches in {file_path}). "
                "Add surrounding context to disambiguate, or set replace_all=true."
            )

        new_content = (
            content.replace(old_string, new_string)
            if replace_all
            else content.replace(old_string, new_string, 1)
        )

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except OSError as e:
            return f"[Error] Could not write {file_path}: {e}"

        return f"[Edited] {file_path} ({count if replace_all else 1} replacement(s))"