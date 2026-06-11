import logging

from app.adapters.tools.base import BaseTool
from app.adapters.tools.registry import register_tool
from app.adapters.tools._task_scope import task_list_id, open_blocked_by
from app.db.deps import get_db

logger = logging.getLogger("agentzoo.tool.task_list")


@register_tool
class TaskListTool(BaseTool):
    name = "task_list"
    description = (
        "List all tasks in your task list. Use this to see what work is "
        "available, check overall progress, and find tasks that are blocked by "
        "unresolved dependencies. Prefer working on tasks in id order. A task is "
        "ready to start when its 'blocked by' list is empty (blockers that are "
        "completed drop off automatically)."
    )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }

    async def execute(self) -> str:
        db = get_db()
        list_id = task_list_id(self.session_id)
        tasks = await db.list_tasks(list_id)
        if not tasks:
            return "No tasks. Use task_create to add one."

        by_id = {t.id: t for t in tasks}
        lines = []
        for t in tasks:
            parts = [f"#{t.id} [{t.status.value}] {t.subject}"]
            if t.owner:
                parts.append(f"(owner: {t.owner})")
            blocked = open_blocked_by(t, by_id)
            if blocked:
                parts.append(
                    "[blocked by " + ", ".join(f"#{b}" for b in blocked) + "]"
                )
            lines.append(" ".join(parts))
        return "\n".join(lines)
