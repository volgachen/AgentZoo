import asyncio
import json
import logging
import shutil
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from app.db.interface import IAgentDatabase
from app.db.deps import get_db
from app.models.domain import Session, SessionStatus, MessageRole, AgentType
from app.adapters.registry import AdapterRegistry, get_registry
from app.adapters.claude_code import ClaudeCodeAdapter
from app.adapters.openai_tool_use import OpenAIToolUseAdapter
from app.core.runner import SessionRunner

logger = logging.getLogger("agentzoo.sessions")
router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    agent_id: str
    working_dir: str | None = None
    # When set, the server copies template_dir -> working_dir before starting
    # the adapter. working_dir must not already exist in that case.
    template_dir: str | None = None
    # Optional .env contents written into working_dir after the template copy
    # (so it overrides any template-provided .env). Requires working_dir.
    env: str | None = None
    # Session that is spawning this one (the caller's own session id). Recorded
    # on the new Session and injected into its .env as PARENT_SESSION_ID so the
    # child can report results back to its parent.
    parent_session_id: str | None = None


class PostMessageRequest(BaseModel):
    content: str
    from_session_id: str | None = None


@router.post("", response_model=Session, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    db: IAgentDatabase = Depends(get_db),
    registry: AdapterRegistry = Depends(get_registry),
):
    logger.info(
        "create_session agent=%s working_dir=%s template_dir=%s parent=%s",
        body.agent_id, body.working_dir, body.template_dir, body.parent_session_id,
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

    working_dir = body.working_dir
    if body.template_dir:
        if not working_dir:
            raise HTTPException(
                status_code=400,
                detail="working_dir is required when template_dir is set (it is the copy target)",
            )
        src = Path(body.template_dir)
        dst = Path(working_dir)
        if not src.is_dir():
            raise HTTPException(status_code=400, detail=f"template_dir does not exist: {src}")
        if dst.exists():
            raise HTTPException(
                status_code=409,
                detail=f"working_dir already exists, refusing to overwrite: {dst}",
            )
        try:
            shutil.copytree(src, dst)
        except (OSError, shutil.Error) as e:
            logger.exception("copytree failed src=%s dst=%s", src, dst)
            raise HTTPException(status_code=500, detail=f"copy failed: {e}")
        working_dir = str(dst.resolve())
        logger.info("copied template %s -> %s", src, working_dir)

    if body.env is not None and not working_dir:
        raise HTTPException(
            status_code=400,
            detail="working_dir is required when env is set (it is the file destination)",
        )

    session = await db.create_session(
        body.agent_id,
        working_dir=working_dir,
        parent_session_id=body.parent_session_id,
    )
    logger.debug("session created id=%s status=%s", session.id, session.status)

    # Write .env into working_dir if we have one. Always include MY_SESSION_ID
    # so the agent can address itself when calling other sessions via the
    # gateway, and PARENT_SESSION_ID (when spawned by another session) so it can
    # report back. Operator-supplied env content goes first; the injected lines
    # follow so they win on duplicate keys when sourced with `set -a`.
    if working_dir:
        env_lines: list[str] = []
        if body.env is not None:
            env_lines.append(body.env if body.env.endswith("\n") else body.env + "\n")
        if session.parent_session_id is not None:
            env_lines.append(f"PARENT_SESSION_ID={session.parent_session_id}\n")
        env_lines.append(f"MY_SESSION_ID={session.id}\n")
        env_path = Path(working_dir) / ".env"
        try:
            env_path.write_text("".join(env_lines), encoding="utf-8")
        except OSError as e:
            logger.exception("failed to write .env to %s", env_path)
            raise HTTPException(status_code=500, detail=f"write .env failed: {e}")
        logger.info("wrote .env to %s", env_path)

    if agent.agent_type == AgentType.CLAUDE_CODE:
        adapter = ClaudeCodeAdapter(working_dir=working_dir, session_id=session.id)
        try:
            await adapter.start(agent.system_prompt)
        except RuntimeError as e:
            logger.exception("ClaudeCodeAdapter start failed for session=%s", session.id)
            await db.update_session_status(session.id, SessionStatus.ERROR)
            raise HTTPException(status_code=500, detail=str(e))
        runner = SessionRunner(session.id, adapter, db)
        await runner.start()
        registry.register(session.id, runner)
        logger.info("registered ClaudeCodeAdapter runner for session=%s", session.id)
    elif agent.agent_type == AgentType.TOOL_USE:
        adapter = OpenAIToolUseAdapter(
            tool_names=agent.tool_names,
            model=agent.openai_model,
            base_url=agent.openai_base_url,
            session_id=session.id,
        )
        try:
            await adapter.start(agent.system_prompt)
        except (ValueError, RuntimeError) as e:
            logger.exception("OpenAIToolUseAdapter start failed for session=%s", session.id)
            await db.update_session_status(session.id, SessionStatus.ERROR)
            raise HTTPException(status_code=500, detail=str(e))
        runner = SessionRunner(session.id, adapter, db)
        await runner.start()
        registry.register(session.id, runner)
        logger.info(
            "registered OpenAIToolUseAdapter runner for session=%s tools=%s",
            session.id, agent.tool_names,
        )

    await db.update_session_status(session.id, SessionStatus.RUNNING)
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
        await db.get_session(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    try:
        runner = registry.get(session_id)
    except KeyError:
        raise HTTPException(status_code=409, detail="session has no live adapter")
    logger.info("HTTP submit session=%s len=%d from=%s",
                session_id, len(body.content), body.from_session_id)
    await runner.submit(body.content, from_session_id=body.from_session_id)
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
    await db.update_session_status(session_id, SessionStatus.COMPLETED)


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

    try:
        runner = registry.get(session_id)
    except KeyError:
        logger.warning("WS session=%s has no live runner (post-restart?)", session_id)
        await _stub_loop(ws, session_id, db)
        return

    async def inbound() -> None:
        while True:
            raw = await ws.receive_text()
            payload = json.loads(raw)
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
            await db.add_message(session_id, MessageRole.USER, content)
            stub = f"[stub] Received: {content}"
            await db.add_message(session_id, MessageRole.AGENT, stub)
            await ws.send_text(json.dumps({"type": "agent_message", "data": stub}))
    except WebSocketDisconnect:
        logger.info("WS disconnect (stub) session=%s", session_id)
