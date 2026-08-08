import logging
import re
import shutil
import subprocess
from pathlib import Path

from fastapi import HTTPException

from app.config import get_settings

logger = logging.getLogger("augentia.workspace")


def slugify_folder_name(value: str | None) -> str:
    if not value:
        return "source"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip(".-_")
    return slug[:48] or "source"


def worktree_root() -> Path:
    root = Path(get_settings().worktree_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def target_dir_for_session(root: Path, source: Path, session_id: str) -> Path:
    candidate = root / f"{slugify_folder_name(source.name)}-{session_id[:8]}"
    if candidate.exists():
        raise HTTPException(
            status_code=409,
            detail=f"working directory already exists, refusing to overwrite: {candidate}",
        )
    return candidate


def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def ensure_git_repository(path: Path) -> None:
    result = run_git(["rev-parse", "--show-toplevel"], path)
    if result.returncode != 0:
        raise HTTPException(
            status_code=400,
            detail=f"selected directory is not inside a Git repository: {path}",
        )


def copy_workspace(source_dir: Path, target_dir: Path) -> None:
    try:
        shutil.copytree(source_dir, target_dir)
    except (OSError, shutil.Error) as e:
        logger.exception("copytree failed src=%s dst=%s", source_dir, target_dir)
        raise HTTPException(status_code=500, detail=f"copy failed: {e}")
    logger.info("copied source directory %s -> %s", source_dir, target_dir)


def create_git_worktree(source_dir: Path, target_dir: Path) -> None:
    ensure_git_repository(source_dir)
    branch = f"augentia/{target_dir.name}"
    result = run_git(["worktree", "add", "-b", branch, str(target_dir)], source_dir)
    if result.returncode != 0:
        logger.warning(
            "git worktree add with branch failed cwd=%s target=%s stderr=%s",
            source_dir,
            target_dir,
            result.stderr,
        )
        fallback = run_git(["worktree", "add", str(target_dir)], source_dir)
        if fallback.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"git worktree creation failed: {fallback.stderr or fallback.stdout}",
            )
