from typing import List
from fastapi import APIRouter, Depends, HTTPException
from app.db.interface import IAgentDatabase
from app.db.deps import get_db
from app.models.domain import AgentTemplate

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=List[AgentTemplate])
async def list_agents(db: IAgentDatabase = Depends(get_db)):
    return await db.list_agents()


@router.get("/{agent_id}", response_model=AgentTemplate)
async def get_agent(agent_id: str, db: IAgentDatabase = Depends(get_db)):
    try:
        return await db.get_agent(agent_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
