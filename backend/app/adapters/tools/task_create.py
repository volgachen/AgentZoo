import logging

from app.adapters.tools.base import BaseTool
from app.adapters.tools.registry import register_tool
from app.adapters.tools._task_scope import task_list_id
from app.db.deps import get_db

logger = logging.getLogger("agentzoo.tool.task_create")


@register_tool
class TaskCreateTool(BaseTool):
    name = "task_create"
    description = (
        "Create a task in your task list to track work. Tasks are scoped to your "
        "session, so use this to organize complex multi-step work and track "
        "progress as you go.\n\n"
        "Use this proactively for: complex multi-step tasks (3+ steps), work the "
        "user provided as a list, or whenever tracking progress is useful. A new "
        "task starts with status 'pending'. After creating tasks, use "
        "task_update to set dependencies (add_blocked_by) or mark progress "
        "(in_progress / completed)."
    )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": (
                        "A brief, actionable title in imperative form "
                        "(e.g. 'Fix authentication bug in login flow')."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "What needs to be done.",
                },
                "active_form": {
                    "type": "string",
                    "description": (
                        "Present-continuous form shown while the task is "
                        "in_progress (e.g. 'Fixing authentication bug')."
                    ),
                },
                "metadata": {
                    "type": "object",
                    "description": "Arbitrary metadata to attach to the task.",
                    "additionalProperties": True,
                },
            },
            "required": ["subject", "description"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        subject: str,
        description: str,
        active_form: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        db = get_db()
        list_id = task_list_id(self.session_id)
        task = await db.create_task(
            list_id,
            subject,
            description,
            active_form=active_form,
            metadata=metadata,
        )
        logger.info("task_create list=%s id=%s subject=%s", list_id, task.id, subject)
        return f"Task #{task.id} created successfully: {task.subject}"
