from typing import List
from fastapi import APIRouter
import app.adapters.tools  # noqa: F401 — triggers tool registration
from app.adapters.tools.registry import list_available

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=List[str])
async def list_tools():
    return list_available()
