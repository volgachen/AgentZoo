from app.models.domain import Task, TaskStatus

# Sessions without a session_id (standalone / post-restart adapters) share this
# catch-all list so the task tools still function.
_DEFAULT_TASK_LIST_ID = "default"


def task_list_id(session_id: str | None) -> str:
    # Tasks are scoped per individual session: the list id IS the session id.
    return session_id or _DEFAULT_TASK_LIST_ID


def open_blocked_by(task: Task, by_id: dict[str, Task]) -> list[str]:
    # A blocker that is already completed no longer blocks, so the list
    # auto-unblocks as dependencies resolve. by_id maps id -> Task for the list.
    return [
        bid
        for bid in task.blocked_by
        if (b := by_id.get(bid)) is not None and b.status != TaskStatus.COMPLETED
    ]
