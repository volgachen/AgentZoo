import json
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from app.db.interface import IAgentDatabase
from app.db.deps import get_db
from app.models.domain import Session, SessionStatus, MessageRole, AgentType
from app.adapters.registry import AdapterRegistry, get_registry
from app.adapters.claude_code import ClaudeCodeAdapter
from app.adapters.base import StreamEventType

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    agent_id: str
    initial_prompt: str = ""


@router.post("", response_model=Session, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    db: IAgentDatabase = Depends(get_db),
    registry: AdapterRegistry = Depends(get_registry),
):
    try:
        agent = await db.get_agent(body.agent_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    session = await db.create_session(body.agent_id)

    if agent.agent_type == AgentType.CLAUDE_CODE:
        adapter = ClaudeCodeAdapter()
        try:
            await adapter.start(agent.system_prompt)
        except RuntimeError as e:
            await db.update_session_status(session.id, SessionStatus.ERROR)
            raise HTTPException(status_code=500, detail=str(e))
        registry.register(session.id, adapter)

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

    try:
        session = await db.get_session(session_id)
    except KeyError:
        await ws.send_text(json.dumps({"type": "error", "data": f"Session '{session_id}' not found"}))
        await ws.close()
        return

    await ws.send_text(json.dumps({"type": "session_state", "data": session.model_dump(mode="json")}))

    try:
        adapter = registry.get(session_id)
    except KeyError:
        # Session exists but has no adapter (e.g. tool_use agent — handled later)
        adapter = None

    try:
        while True:
            # Wait for incoming user message
            raw = await ws.receive_text()
            payload = json.loads(raw)
            user_content = payload.get("content", "")
            await db.add_message(session_id, MessageRole.USER, user_content)

            if adapter is None:
                # Stub for non-Claude-Code agents until tool_use adapter is built
                stub = f"[stub] Received: {user_content}"
                await db.add_message(session_id, MessageRole.AGENT, stub)
                await ws.send_text(json.dumps({"type": "agent_message", "data": stub}))
                continue

            await adapter.send(user_content)

            # Stream adapter output back to client until DONE/ERROR
            agent_buf: list[str] = []
            async for event in adapter.stream():
                await ws.send_text(event.model_dump_json())
                if event.type == StreamEventType.TEXT:
                    agent_buf.append(event.data)
                elif event.type == StreamEventType.ERROR:
                    await db.update_session_status(session_id, SessionStatus.ERROR)
                    break

            if agent_buf:
                await db.add_message(session_id, MessageRole.AGENT, "\n".join(agent_buf))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        await ws.send_text(json.dumps({"type": "error", "data": str(e)}))
        await ws.close()
