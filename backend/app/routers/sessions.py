import json
import logging
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from app.db.interface import IAgentDatabase
from app.db.deps import get_db
from app.models.domain import Session, SessionStatus, MessageRole, AgentType
from app.adapters.registry import AdapterRegistry, get_registry
from app.adapters.claude_code import ClaudeCodeAdapter
from app.adapters.openai_tool_use import OpenAIToolUseAdapter
from app.adapters.base import StreamEventType

logger = logging.getLogger("agentzoo.sessions")
router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    agent_id: str
    initial_prompt: str = ""
    working_dir: str | None = None


@router.post("", response_model=Session, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    db: IAgentDatabase = Depends(get_db),
    registry: AdapterRegistry = Depends(get_registry),
):
    logger.info("create_session agent=%s working_dir=%s", body.agent_id, body.working_dir)
    try:
        agent = await db.get_agent(body.agent_id)
    except KeyError as e:
        logger.warning("create_session: agent not found: %s", body.agent_id)
        raise HTTPException(status_code=404, detail=str(e))

    session = await db.create_session(body.agent_id, working_dir=body.working_dir)
    logger.debug("session created id=%s status=%s", session.id, session.status)

    if agent.agent_type == AgentType.CLAUDE_CODE:
        adapter = ClaudeCodeAdapter(working_dir=body.working_dir)
        try:
            await adapter.start(agent.system_prompt)
        except RuntimeError as e:
            logger.exception("ClaudeCodeAdapter start failed for session=%s", session.id)
            await db.update_session_status(session.id, SessionStatus.ERROR)
            raise HTTPException(status_code=500, detail=str(e))
        registry.register(session.id, adapter)
        logger.info("registered ClaudeCodeAdapter for session=%s", session.id)
    elif agent.agent_type == AgentType.TOOL_USE:
        adapter = OpenAIToolUseAdapter(
            tool_names=agent.tool_names,
            model=agent.openai_model,
            base_url=agent.openai_base_url,
        )
        try:
            await adapter.start(agent.system_prompt)
        except (ValueError, RuntimeError) as e:
            logger.exception("OpenAIToolUseAdapter start failed for session=%s", session.id)
            await db.update_session_status(session.id, SessionStatus.ERROR)
            raise HTTPException(status_code=500, detail=str(e))
        registry.register(session.id, adapter)
        logger.info(
            "registered OpenAIToolUseAdapter for session=%s tools=%s",
            session.id, agent.tool_names,
        )

    if body.initial_prompt:
        await db.add_message(session.id, MessageRole.USER, body.initial_prompt)

    await db.update_session_status(session.id, SessionStatus.RUNNING)
    return await db.get_session(session.id)


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
        adapter = registry.get(session_id)
    except KeyError:
        adapter = None
        logger.warning("WS session=%s has no live adapter (post-restart?)", session_id)

    try:
        while True:
            raw = await ws.receive_text()
            payload = json.loads(raw)
            user_content = payload.get("content", "")
            logger.info("WS recv session=%s len=%d", session_id, len(user_content))
            logger.debug("WS recv session=%s content=%r", session_id, user_content)
            await db.add_message(session_id, MessageRole.USER, user_content)

            if adapter is None:
                stub = f"[stub] Received: {user_content}"
                await db.add_message(session_id, MessageRole.AGENT, stub)
                await ws.send_text(json.dumps({"type": "agent_message", "data": stub}))
                continue

            await adapter.send(user_content)

            agent_buf: list[str] = []
            event_count = 0
            async for event in adapter.stream():
                event_count += 1
                logger.debug("WS send session=%s event=%s data=%r",
                             session_id, event.type, event.data[:200])
                await ws.send_text(event.model_dump_json())
                if event.type == StreamEventType.TEXT:
                    agent_buf.append(event.data)
                elif event.type == StreamEventType.ERROR:
                    logger.error("session=%s adapter ERROR event: %s", session_id, event.data)
                    await db.update_session_status(session_id, SessionStatus.ERROR)
                    break
            logger.info("WS turn done session=%s events=%d", session_id, event_count)

            if agent_buf:
                await db.add_message(session_id, MessageRole.AGENT, "\n".join(agent_buf))

    except WebSocketDisconnect:
        logger.info("WS disconnect session=%s", session_id)
    except Exception as e:
        logger.exception("WS unexpected error session=%s", session_id)
        await ws.send_text(json.dumps({"type": "error", "data": str(e)}))
        await ws.close()
