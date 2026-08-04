import asyncio
import json
import logging
import re
import shutil
import subprocess
import uuid
from enum import Enum
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from app.config import get_settings
from app.db.interface import IAgentDatabase
from app.db.deps import get_db
from app.models.domain import Session, SessionStatus, MessageRole, AgentType, AgentTemplate
from app.adapters.registry import AdapterRegistry, get_registry
from app.adapters.claude_code import ClaudeCodeAdapter
from app.adapters.openai_tool_use import OpenAIToolUseAdapter
from app.core.runner import SessionRunner
from app.core.session_config import ensure_session_config, write_session_config
from app.adapters.tools.permissions import explain_tool_permission, validate_tool_permissions_config

logger = logging.getLogger("augentia.sessions")
router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateMode(str, Enum):
    USE_EXISTING_DIRECTORY = "use_existing_directory"
    DUPLICATE_BY_COPY = "duplicate_by_copy"
    GIT_WORKTREE = "git_worktree"


class CreateSessionRequest(BaseModel):
    agent_id: str
    # Optional friendly label. When omitted, the DB seeds one from the agent
    # name + creation time. Spawned sub-sessions pass their task description here.
    title: str | None = None
    # Directory selected by the user. For use_existing_directory it becomes the
    # final working directory. For copy/worktree modes it is the source used to
    # create a new final working directory under AUGENTIA_WORKTREE_ROOT.
    source_dir: str | None = None
    create_mode: CreateMode = CreateMode.USE_EXISTING_DIRECTORY
    # Session that is spawning this one (the caller's own session id). Recorded
    # on the new Session and exported to child processes as PARENT_SESSION_ID so
    # the child can report results back to its parent.
    parent_session_id: str | None = None
    # Additional system prompt content appended to the agent's base system_prompt.
    # Applied before additional_prompt_path.
    additional_prompt: str | None = None
    # Path to a file containing additional system prompt content. The file is
    # read and appended to the agent's base system_prompt (after additional_prompt).
    additional_prompt_path: str | None = None


class UpdateSessionRequest(BaseModel):
    title: str


class UpdateSessionConfigRequest(BaseModel):
    config: dict


class TestToolPermissionRequest(BaseModel):
    tool: str
    path: str | None = None
    args: dict | None = None


class PostMessageRequest(BaseModel):
    content: str
    from_session_id: str | None = None


class RetryMessageRequest(BaseModel):
    content: str


async def _build_runner(
    session: Session,
    agent: AgentTemplate,
    db: IAgentDatabase,
    registry: AdapterRegistry,
    additional_prompt: str | None = None,
    additional_prompt_path: str | None = None,
) -> SessionRunner:
    """Construct + start the adapter and its runner, register it, and replay any
    persisted conversation. Shared by create_session (fresh, no history) and the
    post-restart rehydration path (history restored from the DB). Raises
    ValueError/RuntimeError on adapter start failure; the caller decides how to
    surface that."""
    session_config = ensure_session_config(session.id, agent.config)
    if agent.agent_type == AgentType.CLAUDE_CODE:
        adapter = ClaudeCodeAdapter(working_dir=session.working_dir, session_id=session.id)
    elif agent.agent_type == AgentType.TOOL_USE:
        adapter = OpenAIToolUseAdapter(
            tool_names=agent.tool_names,
            model=agent.openai_model,
            base_url=agent.openai_base_url,
            session_id=session.id,
            working_dir=session.working_dir,
            config=session_config,
        )
    else:
        raise RuntimeError(f"unsupported agent_type: {agent.agent_type}")

    # Build the final system prompt by appending additional content
    system_prompt = agent.system_prompt
    if additional_prompt:
        system_prompt = system_prompt + "\n\n" + additional_prompt
    if additional_prompt_path:
        try:
            extra_content = Path(additional_prompt_path).read_text(encoding="utf-8")
            system_prompt = system_prompt + "\n\n" + extra_content
        except (OSError, UnicodeDecodeError) as e:
            logger.exception("failed to read additional_prompt_path=%s", additional_prompt_path)
            raise ValueError(f"failed to read additional system prompt from {additional_prompt_path}: {e}")

    await adapter.start(system_prompt)

    # Rebuild prior context so a session rehydrated after a restart isn't
    # amnesiac. No-op for a fresh session (no rows) or adapters that don't
    # override restore_history.
    history = await db.get_messages(session.id)
    if history:
        await adapter.restore_history(history)

    runner = SessionRunner(session.id, adapter, db)
    await runner.start()
    registry.register(session.id, runner)
    return runner


def _slugify_folder_name(value: str | None) -> str:
    if not value:
        return "source"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip(".-_")
    return slug[:48] or "source"


def _worktree_root() -> Path:
    root = Path(get_settings().worktree_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _target_dir_for_session(root: Path, source: Path, session_id: str) -> Path:
    source_name = _slugify_folder_name(source.name)
    candidate = root / f"{source_name}-{session_id[:8]}"
    if candidate.exists():
        raise HTTPException(
            status_code=409,
            detail=f"working directory already exists, refusing to overwrite: {candidate}",
        )
    return candidate


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _ensure_git_repository(path: Path) -> None:
    result = _run_git(["rev-parse", "--show-toplevel"], path)
    if result.returncode != 0:
        raise HTTPException(
            status_code=400,
            detail=f"selected directory is not inside a Git repository: {path}",
        )


def _create_git_worktree(source_dir: Path, target_dir: Path) -> None:
    _ensure_git_repository(source_dir)
    branch = f"augentia/{target_dir.name}"
    result = _run_git(["worktree", "add", "-b", branch, str(target_dir)], source_dir)
    if result.returncode != 0:
        logger.warning(
            "git worktree add with branch failed cwd=%s target=%s stderr=%s",
            source_dir, target_dir, result.stderr,
        )
        fallback = _run_git(["worktree", "add", str(target_dir)], source_dir)
        if fallback.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"git worktree creation failed: {fallback.stderr or fallback.stdout}",
            )


async def _get_or_rehydrate(
    session: Session,
    db: IAgentDatabase,
    registry: AdapterRegistry,
) -> SessionRunner | None:
    """Return the live runner, rebuilding it from persisted state if the
    in-memory registry lost it to a backend restart. Returns None when the
    session can't be rehydrated (claude-code continuity isn't restored yet) so
    callers fall back to the stub / 409."""
    try:
        return registry.get(session.id)
    except KeyError:
        pass
    agent = await db.get_agent(session.agent_id)
    if agent.agent_type != AgentType.TOOL_USE:
        return None
    logger.info("rehydrating runner for session=%s", session.id)
    try:
        # Replay the per-session prompt overrides that were stored on the
        # session row when it was first created, so the rehydrated adapter
        # sees the same effective system prompt it had pre-restart. Inline
        # text is restored verbatim; the path is re-read from disk (its
        # contents may have changed since launch — that's intentional, the
        # path is the contract, not a snapshot).
        return await _build_runner(
            session, agent, db, registry,
            additional_prompt=session.additional_prompt,
            additional_prompt_path=session.additional_prompt_path,
        )
    except (ValueError, RuntimeError):
        logger.exception("rehydrate failed session=%s", session.id)
        await db.update_session_status(session.id, SessionStatus.ERROR)
        return None


@router.post("", response_model=Session, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    db: IAgentDatabase = Depends(get_db),
    registry: AdapterRegistry = Depends(get_registry),
):
    logger.info(
        "create_session agent=%s source_dir=%s create_mode=%s parent=%s",
        body.agent_id, body.source_dir, body.create_mode, body.parent_session_id,
    )
    try:
        agent = await db.get_agent(body.agent_id)
    except KeyError as e:
        logger.warning("create_session: agent not found: %s", body.agent_id)
        raise HTTPException(status_code=404, detail=str(e))

    if body.parent_session_id is not None:
        try:
            await db.get_session(body.parent_session_id)
        except KeyError:
            logger.warning("create_session: parent session not found: %s", body.parent_session_id)
            raise HTTPException(
                status_code=404,
                detail=f"parent_session_id '{body.parent_session_id}' not found",
            )

    session_id = str(uuid.uuid4())

    source: Path | None = None
    if body.source_dir:
        source = Path(body.source_dir).expanduser().resolve()
        if not source.is_dir():
            raise HTTPException(status_code=400, detail=f"source_dir does not exist: {source}")

    if body.create_mode == CreateMode.USE_EXISTING_DIRECTORY:
        working_dir = str(source) if source else None
    elif body.create_mode in (CreateMode.DUPLICATE_BY_COPY, CreateMode.GIT_WORKTREE):
        if source is None:
            raise HTTPException(
                status_code=400,
                detail="source_dir is required for copy/worktree modes",
            )
        target = _target_dir_for_session(_worktree_root(), source, session_id)
        if body.create_mode == CreateMode.DUPLICATE_BY_COPY:
            try:
                shutil.copytree(source, target)
            except (OSError, shutil.Error) as e:
                logger.exception("copytree failed src=%s dst=%s", source, target)
                raise HTTPException(status_code=500, detail=f"copy failed: {e}")
            logger.info("copied source directory %s -> %s", source, target)
        else:
            _create_git_worktree(source, target)
            logger.info("created git worktree from %s -> %s", source, target)
        working_dir = str(target.resolve())
    else:
        raise HTTPException(status_code=400, detail=f"unsupported create_mode: {body.create_mode}")

    session = await db.create_session(
        body.agent_id,
        working_dir=working_dir,
        session_id=session_id,
        title=body.title,
        parent_session_id=body.parent_session_id,
        additional_prompt=body.additional_prompt,
        additional_prompt_path=body.additional_prompt_path,
    )
    logger.debug("session created id=%s status=%s", session.id, session.status)

    try:
        await _build_runner(
            session, agent, db, registry,
            additional_prompt=body.additional_prompt,
            additional_prompt_path=body.additional_prompt_path,
        )
    except (ValueError, RuntimeError) as e:
        logger.exception("adapter start failed for session=%s", session.id)
        await db.update_session_status(session.id, SessionStatus.ERROR)
        raise HTTPException(status_code=500, detail=str(e))
    logger.info("registered runner for session=%s type=%s", session.id, agent.agent_type)

    # The adapter is now live, but no turn is running until a user message is
    # submitted. Mark the session as waiting for user input rather than RUNNING
    # so status consistently means turn execution state, not adapter liveness.
    await db.update_session_status(session.id, SessionStatus.WAITING_USER)
    return await db.get_session(session.id)


@router.get("", response_model=list[Session])
async def list_sessions(db: IAgentDatabase = Depends(get_db)):
    return await db.list_sessions()


@router.get("/{session_id}", response_model=Session)
async def get_session(session_id: str, db: IAgentDatabase = Depends(get_db)):
    try:
        return await db.get_session(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{session_id}", response_model=Session)
async def rename_session(
    session_id: str,
    body: UpdateSessionRequest,
    db: IAgentDatabase = Depends(get_db),
):
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title must not be empty")
    try:
        return await db.update_session_title(session_id, title)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{session_id}/config")
async def get_session_config(
    session_id: str,
    db: IAgentDatabase = Depends(get_db),
):
    try:
        session = await db.get_session(session_id)
        agent = await db.get_agent(session.agent_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    try:
        return ensure_session_config(session_id, agent.config)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{session_id}/config")
async def update_session_config(
    session_id: str,
    body: UpdateSessionConfigRequest,
    db: IAgentDatabase = Depends(get_db),
    registry: AdapterRegistry = Depends(get_registry),
):
    try:
        session = await db.get_session(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    try:
        validate_tool_permissions_config(body.config.get("tool_permissions"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    config = write_session_config(session_id, body.config)
    try:
        runner = registry.get(session_id)
    except KeyError:
        runner = None
    if runner is not None:
        await runner.reload_config(config)
    return config


@router.post("/{session_id}/tool-permissions/test")
async def test_tool_permission(
    session_id: str,
    body: TestToolPermissionRequest,
    db: IAgentDatabase = Depends(get_db),
):
    try:
        session = await db.get_session(session_id)
        agent = await db.get_agent(session.agent_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    config = ensure_session_config(session_id, agent.config)
    args = dict(body.args or {})
    if body.path is not None:
        if body.tool == "read":
            args.setdefault("path", body.path)
        else:
            args.setdefault("file_path", body.path)
    explanation = explain_tool_permission(body.tool, args, session.working_dir, config)
    if explanation is None:
        return {
            "action": "ask",
            "reason": "tool is not covered by tool_permissions; using legacy approval policy",
            "rule_id": None,
            "resolved_path": None,
        }
    return {
        "action": explanation.action,
        "reason": explanation.reason,
        "rule_id": explanation.rule_id,
        "resolved_path": explanation.resolved_path,
    }


@router.get("/{session_id}/messages")
async def get_messages(session_id: str, db: IAgentDatabase = Depends(get_db)):
    try:
        return await db.get_messages(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{session_id}/messages", status_code=202)
async def post_message(
    session_id: str,
    body: PostMessageRequest,
    db: IAgentDatabase = Depends(get_db),
    registry: AdapterRegistry = Depends(get_registry),
):
    try:
        session = await db.get_session(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    runner = await _get_or_rehydrate(session, db, registry)
    if runner is None:
        raise HTTPException(status_code=409, detail="session has no live adapter")
    logger.info("HTTP submit session=%s len=%d from=%s",
                session_id, len(body.content), body.from_session_id)
    await runner.submit(body.content, from_session_id=body.from_session_id)
    return {"status": "queued"}


@router.post("/{session_id}/messages/{message_id}/retry", status_code=202)
async def retry_from_message(
    session_id: str,
    message_id: str,
    body: RetryMessageRequest,
    db: IAgentDatabase = Depends(get_db),
    registry: AdapterRegistry = Depends(get_registry),
):
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="content must not be empty")
    try:
        session = await db.get_session(session_id)
        messages = await db.get_messages(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    target = next((m for m in messages if m.id == message_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Message '{message_id}' not found")
    if target.role != MessageRole.USER:
        raise HTTPException(status_code=400, detail="only user messages can be retried")
    agent = await db.get_agent(session.agent_id)
    if agent.agent_type != AgentType.TOOL_USE:
        raise HTTPException(
            status_code=409,
            detail="retrying from history is currently supported only for tool_use sessions",
        )
    await db.soft_delete_messages_from(session_id, message_id)

    # Drop any in-memory context that still contains the deleted suffix, then
    # rebuild it from the now-filtered persisted history before submitting the
    # edited user turn.
    await registry.remove(session_id)
    runner = await _get_or_rehydrate(session, db, registry)
    if runner is None:
        raise HTTPException(status_code=409, detail="session has no live adapter")
    logger.info("HTTP retry session=%s message=%s len=%d", session_id, message_id, len(content))
    await runner.submit(content)
    return {"status": "queued"}


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    db: IAgentDatabase = Depends(get_db),
    registry: AdapterRegistry = Depends(get_registry),
):
    logger.info("delete_session id=%s", session_id)
    try:
        await db.get_session(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    await registry.remove(session_id)
    await db.soft_delete_session(session_id)


@router.websocket("/{session_id}/stream")
async def session_stream(
    session_id: str,
    ws: WebSocket,
    db: IAgentDatabase = Depends(get_db),
    registry: AdapterRegistry = Depends(get_registry),
):
    await ws.accept()
    logger.info("WS connect session=%s", session_id)

    try:
        session = await db.get_session(session_id)
    except KeyError:
        logger.warning("WS rejected: session not found id=%s", session_id)
        await ws.send_text(json.dumps({"type": "error", "data": f"Session '{session_id}' not found"}))
        await ws.close()
        return

    await ws.send_text(json.dumps({"type": "session_state", "data": session.model_dump(mode="json")}))

    runner = await _get_or_rehydrate(session, db, registry)
    if runner is None:
        logger.warning("WS session=%s has no live runner (post-restart, stub)", session_id)
        await _stub_loop(ws, session_id, db)
        return

    async def inbound() -> None:
        while True:
            raw = await ws.receive_text()
            payload = json.loads(raw)
            # A client frame is either a new user turn ({"content": ...}) or a
            # decision on a pending tool confirm ({"decision": "approve"|"deny",
            # "call_id": ..., "message": ...}). The latter only resolves an adapter
            # Future, and may also queue a supplementary user message.
            if "decision" in payload:
                call_id = payload.get("call_id")
                approved = payload.get("decision") == "approve"
                supplementary_msg = payload.get("message", "").strip()
                if call_id:
                    logger.info("WS decision session=%s call_id=%s approved=%s has_message=%s",
                                session_id, call_id, approved, bool(supplementary_msg))
                    await runner.resolve_decision(call_id, approved, supplementary_msg)
                continue
            content = payload.get("content", "")
            logger.info("WS recv session=%s len=%d", session_id, len(content))
            await runner.submit(content)

    async def outbound() -> None:
        async with runner.subscribe() as events:
            async for event in events:
                await ws.send_text(event.model_dump_json())

    inbound_task = asyncio.create_task(inbound())
    outbound_task = asyncio.create_task(outbound())
    try:
        done, pending = await asyncio.wait(
            {inbound_task, outbound_task},
            return_when=asyncio.FIRST_EXCEPTION,
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                raise exc
    except WebSocketDisconnect:
        logger.info("WS disconnect session=%s", session_id)
    except Exception as e:
        logger.exception("WS unexpected error session=%s", session_id)
        try:
            await ws.send_text(json.dumps({"type": "error", "data": str(e)}))
            await ws.close()
        except Exception:
            pass
    finally:
        for task in (inbound_task, outbound_task):
            if not task.done():
                task.cancel()


async def _stub_loop(ws: WebSocket, session_id: str, db: IAgentDatabase) -> None:
    """Fallback when no live runner exists (post-restart). Echo only."""
    try:
        while True:
            raw = await ws.receive_text()
            payload = json.loads(raw)
            content = payload.get("content", "")
            await db.get_session(session_id)
            await db.add_message(session_id, MessageRole.USER, content)
            stub = f"[stub] Received: {content}"
            await db.add_message(session_id, MessageRole.AGENT, stub)
            await ws.send_text(json.dumps({"type": "agent_message", "data": stub}))
    except WebSocketDisconnect:
        logger.info("WS disconnect (stub) session=%s", session_id)
