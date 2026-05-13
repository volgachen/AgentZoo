import logging
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("agentzoo.fs")
router = APIRouter(prefix="/fs", tags=["fs"])


# Repo root = parents[3] of this file: app/routers/fs.py -> app/routers -> app -> backend -> repo
_REPO_ROOT = Path(__file__).resolve().parents[3]
_TEMPLATES_ROOT = _REPO_ROOT / "templates"

_HOME = Path(os.path.expanduser("~")).resolve()
# Don't descend into pseudo-filesystems even when browsing freely.
_BLOCKED_PREFIXES = ("/proc", "/sys", "/dev", "/run")


class DirEntry(BaseModel):
    name: str
    path: str
    is_dir: bool


class BrowseResponse(BaseModel):
    path: str
    parent: str | None
    entries: list[DirEntry]


def _is_blocked(p: Path) -> bool:
    s = str(p)
    return any(s == pref or s.startswith(pref + "/") for pref in _BLOCKED_PREFIXES)


def _list_dir(target: Path, root: Path | None = None) -> BrowseResponse:
    """List subdirectories of `target`. If `root` is given, the listing is
    confined to it: paths outside `root` are rejected and `parent` is None at root."""
    try:
        target = target.resolve(strict=True)
    except (FileNotFoundError, RuntimeError):
        raise HTTPException(status_code=404, detail=f"Path not found: {target}")

    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {target}")

    if root is not None:
        root = root.resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise HTTPException(status_code=403, detail="Path outside allowed root")
    elif _is_blocked(target):
        raise HTTPException(status_code=403, detail="Path is not browsable")

    parent: str | None = None
    if root is not None:
        parent = None if target == root else str(target.parent)
    else:
        parent = None if target == target.parent else str(target.parent)

    entries: list[DirEntry] = []
    try:
        for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            if child.name.startswith("."):
                continue
            try:
                is_dir = child.is_dir()
            except OSError:
                continue
            if not is_dir:
                continue
            if root is None and _is_blocked(child):
                continue
            entries.append(DirEntry(name=child.name, path=str(child), is_dir=True))
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {target}")

    return BrowseResponse(path=str(target), parent=parent, entries=entries)


@router.get("/browse", response_model=BrowseResponse)
async def browse(path: str | None = Query(default=None)):
    target = Path(path) if path else _REPO_ROOT
    return _list_dir(target, root=None)


@router.get("/templates", response_model=BrowseResponse)
async def browse_templates(path: str | None = Query(default=None)):
    if not _TEMPLATES_ROOT.is_dir():
        raise HTTPException(status_code=404, detail=f"Templates root missing: {_TEMPLATES_ROOT}")
    target = Path(path) if path else _TEMPLATES_ROOT
    return _list_dir(target, root=_TEMPLATES_ROOT)


@router.get("/home")
async def home():
    return {
        "home": str(_HOME),
        "project_root": str(_REPO_ROOT),
        "templates_root": str(_TEMPLATES_ROOT),
    }
