from fastapi import APIRouter, Depends, HTTPException

from app.db.deps import get_db
from app.db.interface import IAgentDatabase
from app.models.domain import Task

router = APIRouter(prefix="/sessions", tags=["tasks"])


@router.get("/{session_id}/tasks", response_model=list[Task])
async def list_session_tasks(
    session_id: str, db: IAgentDatabase = Depends(get_db)
):
    # Tasks are scoped per session: the task_list_id is the session id itself.
    try:
        await db.get_session(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return await db.list_tasks(session_id)
