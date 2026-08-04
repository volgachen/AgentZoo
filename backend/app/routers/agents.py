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
    config: dict = Field(default_factory=dict)
    openai_model: str = "gpt-4o"
    openai_base_url: str | None = None


class UpdateAgentRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    system_prompt: str | None = None
    tool_names: list[str] | None = None
    config: dict | None = None
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


def _validate_config(config: dict) -> None:
    approvals = config.get("tool_approvals", {})
    if not isinstance(approvals, dict):
        raise HTTPException(
            status_code=400,
            detail="config.tool_approvals must be an object mapping tool name -> bool",
        )
    _validate_tools(list(approvals.keys()))
    bad = [k for k, v in approvals.items() if not isinstance(v, bool)]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"config.tool_approvals values must be booleans; got non-bool for: {bad}",
        )
    _validate_tool_permissions_config(config.get("tool_permissions"))


def _validate_tool_selector_item(
    tool: object,
    available: set[str],
    supported: set[str],
    field: str,
) -> None:
    if tool != "*" and tool not in available:
        raise HTTPException(status_code=400, detail=f"{field} is unknown: {tool}")
    if tool != "*" and tool not in supported:
        raise HTTPException(
            status_code=400,
            detail=f"{field} is not supported by tool_permissions yet: {tool}",
        )


def _validate_tool_permissions_config(permissions: object) -> None:
    if permissions is None:
        return
    if not isinstance(permissions, dict):
        raise HTTPException(
            status_code=400,
            detail="config.tool_permissions must be an object",
        )

    default = permissions.get("default", "ask")
    if default not in ("allow", "deny", "ask"):
        raise HTTPException(
            status_code=400,
            detail="config.tool_permissions.default must be one of: allow, deny, ask",
        )

    rules = permissions.get("rules", [])
    if not isinstance(rules, list):
        raise HTTPException(
            status_code=400,
            detail="config.tool_permissions.rules must be an array",
        )

    available = set(list_available())
    file_tools = {"read", "write", "edit"}
    for index, rule in enumerate(rules):
        prefix = f"config.tool_permissions.rules[{index}]"
        if not isinstance(rule, dict):
            raise HTTPException(status_code=400, detail=f"{prefix} must be an object")
        effect = rule.get("effect")
        if effect not in ("allow", "deny"):
            raise HTTPException(status_code=400, detail=f"{prefix}.effect must be allow or deny")
        tool = rule.get("tool")
        tools = rule.get("tools")
        if tool is None and tools is None:
            raise HTTPException(status_code=400, detail=f"{prefix} must include tool or tools")
        if tool is not None:
            _validate_tool_selector_item(tool, available, file_tools, f"{prefix}.tool")
        if tools is not None:
            if not isinstance(tools, list) or not tools:
                raise HTTPException(status_code=400, detail=f"{prefix}.tools must be a non-empty array")
            for tool_index, item in enumerate(tools):
                _validate_tool_selector_item(item, available, file_tools, f"{prefix}.tools[{tool_index}]")
        paths = rule.get("paths")
        if not isinstance(paths, list) or not all(isinstance(p, str) and p for p in paths):
            raise HTTPException(
                status_code=400,
                detail=f"{prefix}.paths must be a non-empty string array",
            )
        rule_id = rule.get("id")
        if rule_id is not None and not isinstance(rule_id, str):
            raise HTTPException(status_code=400, detail=f"{prefix}.id must be a string when present")


@router.get("", response_model=List[AgentTemplate])
async def list_agents(db: IAgentDatabase = Depends(get_db)):
    return await db.list_agents()


@router.post("", response_model=AgentTemplate, status_code=201)
async def create_agent(
    body: CreateAgentRequest,
    db: IAgentDatabase = Depends(get_db),
):
    _validate_tools(body.tool_names)
    _validate_config(body.config)
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
    if body.config is not None:
        _validate_config(body.config)

    return await db.update_agent(agent_id, **body.model_dump(exclude_unset=True))


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, db: IAgentDatabase = Depends(get_db)):
    try:
        await db.get_agent(agent_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    await db.delete_agent(agent_id)
