import logging

from app.adapters.tools.base import BaseTool
from app.adapters.tools.registry import register_tool
from app.adapters.tools._task_scope import task_list_id
from app.db.deps import get_db
from app.models.domain import TaskStatus

logger = logging.getLogger("agentzoo.tool.task_update")


@register_tool
class TaskUpdateTool(BaseTool):
    name = "task_update"
    description = (
        "Update a task: change its status, edit fields, set dependencies, assign "
        "an owner, or delete it.\n\n"
        "Status workflow: pending -> in_progress -> completed. Mark a task "
        "in_progress BEFORE starting work and completed only when fully done "
        "(don't mark completed if tests fail or work is partial). Use "
        "status='deleted' to permanently remove a task. Use add_blocked_by to "
        "declare that this task must wait for others, or add_blocks for the "
        "reverse — both sides of the dependency are wired automatically."
    )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The id of the task to update (e.g. '1').",
                },
                "subject": {
                    "type": "string",
                    "description": "New subject (imperative form).",
                },
                "description": {
                    "type": "string",
                    "description": "New description.",
                },
                "active_form": {
                    "type": "string",
                    "description": "New present-continuous form for the spinner.",
                },
                "status": {
                    "type": "string",
                    "description": "New status for the task.",
                    "enum": ["pending", "in_progress", "completed", "deleted"],
                },
                "owner": {
                    "type": "string",
                    "description": "Assign the task to an owner (e.g. an agent name).",
                },
                "add_blocks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Task ids that cannot start until this one completes.",
                },
                "add_blocked_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Task ids that must complete before this one can start.",
                },
                "metadata": {
                    "type": "object",
                    "description": (
                        "Metadata keys to merge into the task. Set a key to null "
                        "to delete it."
                    ),
                    "additionalProperties": True,
                },
            },
            "required": ["task_id"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        task_id: str,
        subject: str | None = None,
        description: str | None = None,
        active_form: str | None = None,
        status: str | None = None,
        owner: str | None = None,
        add_blocks: list[str] | None = None,
        add_blocked_by: list[str] | None = None,
        metadata: dict | None = None,
    ) -> str:
        db = get_db()
        list_id = task_list_id(self.session_id)

        if status == "deleted":
            ok = await db.delete_task(list_id, task_id)
            if not ok:
                return f"Error: Task #{task_id} not found."
            logger.info("task_update delete list=%s id=%s", list_id, task_id)
            return f"Task #{task_id} deleted."

        status_enum: TaskStatus | None = None
        if status is not None:
            try:
                status_enum = TaskStatus(status)
            except ValueError:
                return (
                    f"Error: invalid status '{status}'. Use one of "
                    "pending, in_progress, completed, deleted."
                )

        # owner is only forwarded when supplied, so the DB sentinel leaves it
        # unchanged otherwise (a bare None here means 'not provided').
        kwargs: dict = {}
        if owner is not None:
            kwargs["owner"] = owner

        task = await db.update_task(
            list_id,
            task_id,
            subject=subject,
            description=description,
            active_form=active_form,
            status=status_enum,
            metadata=metadata,
            add_blocks=add_blocks,
            add_blocked_by=add_blocked_by,
            **kwargs,
        )
        if task is None:
            return f"Error: Task #{task_id} not found."

        updated = [
            f for f, v in (
                ("subject", subject),
                ("description", description),
                ("active_form", active_form),
                ("status", status),
                ("owner", owner),
                ("add_blocks", add_blocks),
                ("add_blocked_by", add_blocked_by),
                ("metadata", metadata),
            ) if v is not None
        ]
        logger.info(
            "task_update list=%s id=%s fields=%s", list_id, task_id, updated
        )
        suffix = f" (updated: {', '.join(updated)})" if updated else ""
        return f"Task #{task.id} updated [{task.status.value}]{suffix}"
