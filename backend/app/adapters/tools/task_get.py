import logging

from app.adapters.tools.base import BaseTool
from app.adapters.tools.registry import register_tool
from app.adapters.tools._task_scope import task_list_id, open_blocked_by
from app.db.deps import get_db

logger = logging.getLogger("agentzoo.tool.task_get")


@register_tool
class TaskGetTool(BaseTool):
    name = "task_get"
    description = (
        "Retrieve the full details of a single task by its id: the complete "
        "description, status, owner, and dependency relationships (what it "
        "blocks and what blocks it). Use this before starting work on a task to "
        "get the full requirements and verify it has no unresolved blockers."
    )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The id of the task to retrieve (e.g. '1').",
                },
            },
            "required": ["task_id"],
            "additionalProperties": False,
        }

    async def execute(self, task_id: str) -> str:
        db = get_db()
        list_id = task_list_id(self.session_id)
        task = await db.get_task(list_id, task_id)
        if task is None:
            return f"Error: Task #{task_id} not found."

        by_id = {t.id: t for t in await db.list_tasks(list_id)}
        lines = [
            f"Task #{task.id}",
            f"  subject: {task.subject}",
            f"  status: {task.status.value}",
            f"  description: {task.description}",
        ]
        if task.active_form:
            lines.append(f"  active_form: {task.active_form}")
        if task.owner:
            lines.append(f"  owner: {task.owner}")
        if task.blocks:
            lines.append("  blocks: " + ", ".join(f"#{b}" for b in task.blocks))
        if task.blocked_by:
            open_blockers = open_blocked_by(task, by_id)
            suffix = (
                "" if open_blockers
                else "  (all resolved — ready to start)"
            )
            lines.append(
                "  blocked_by: "
                + ", ".join(f"#{b}" for b in task.blocked_by)
                + (f"  open: {', '.join('#' + b for b in open_blockers)}" if open_blockers else suffix)
            )
        if task.metadata:
            lines.append(f"  metadata: {task.metadata}")
        return "\n".join(lines)
