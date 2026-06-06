from typing import List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.db.interface import IAgentDatabase
from app.db.deps import get_db
from app.models.domain import AgentTemplate, AgentType
import app.adapters.tools  # noqa: F401 — triggers tool registration
from app.adapters.tools.registry import list_available

router = APIRouter(prefix="/agents", tags=["agents"])


class CreateAgentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    agent_type: AgentType
    system_prompt: str = ""
    tool_names: list[str] = Field(default_factory=list)
    openai_model: str = "gpt-4o"
    openai_base_url: str | None = None


class UpdateAgentRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    system_prompt: str | None = None
    tool_names: list[str] | None = None
    openai_model: str | None = None
    openai_base_url: str | None = None


def _validate_tools(names: list[str]) -> None:
    available = list_available()
    unknown = [n for n in names if n not in available]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tools: {unknown}. Available: {available}",
        )


@router.get("", response_model=List[AgentTemplate])
async def list_agents(db: IAgentDatabase = Depends(get_db)):
    return await db.list_agents()


@router.post("", response_model=AgentTemplate, status_code=201)
async def create_agent(
    body: CreateAgentRequest,
    db: IAgentDatabase = Depends(get_db),
):
    _validate_tools(body.tool_names)
    template = AgentTemplate(**body.model_dump())
    return await db.create_agent(template)


@router.get("/{agent_id}", response_model=AgentTemplate)
async def get_agent(agent_id: str, db: IAgentDatabase = Depends(get_db)):
    try:
        return await db.get_agent(agent_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{agent_id}", response_model=AgentTemplate)
async def update_agent(
    agent_id: str,
    body: UpdateAgentRequest,
    db: IAgentDatabase = Depends(get_db),
):
    try:
        await db.get_agent(agent_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if body.tool_names is not None:
        _validate_tools(body.tool_names)

    return await db.update_agent(agent_id, **body.model_dump(exclude_unset=True))


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, db: IAgentDatabase = Depends(get_db)):
    try:
        await db.get_agent(agent_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    await db.delete_agent(agent_id)
