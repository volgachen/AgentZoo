import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.db.deps import get_db
from app.db.interface import IAgentDatabase
from app.models.domain import Plugin, PluginStatus
from app.plugins.registry import PluginRunnerRegistry, get_plugin_registry


logger = logging.getLogger("agentzoo.plugins")
router = APIRouter(prefix="/plugins", tags=["plugins"])


class CreatePluginRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str = ""


class UpdatePluginRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = None


@router.get("", response_model=list[Plugin])
async def list_plugins(db: IAgentDatabase = Depends(get_db)):
    return await db.list_plugins()


@router.post("", response_model=Plugin, status_code=201)
async def create_plugin(
    body: CreatePluginRequest,
    db: IAgentDatabase = Depends(get_db),
):
    return await db.create_plugin(name=body.name, code=body.code)


@router.get("/{plugin_id}", response_model=Plugin)
async def get_plugin(plugin_id: str, db: IAgentDatabase = Depends(get_db)):
    try:
        return await db.get_plugin(plugin_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{plugin_id}", response_model=Plugin)
async def update_plugin(
    plugin_id: str,
    body: UpdatePluginRequest,
    db: IAgentDatabase = Depends(get_db),
    registry: PluginRunnerRegistry = Depends(get_plugin_registry),
):
    try:
        plugin = await db.get_plugin(plugin_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if body.code is not None and plugin.status == PluginStatus.RUNNING:
        raise HTTPException(
            status_code=409,
            detail="Stop the plugin before editing its code.",
        )

    return await db.update_plugin(plugin_id, name=body.name, code=body.code)


@router.delete("/{plugin_id}", status_code=204)
async def delete_plugin(
    plugin_id: str,
    db: IAgentDatabase = Depends(get_db),
    registry: PluginRunnerRegistry = Depends(get_plugin_registry),
):
    try:
        await db.get_plugin(plugin_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    await registry.remove(plugin_id)
    await db.delete_plugin(plugin_id)


@router.post("/{plugin_id}/start", response_model=Plugin)
async def start_plugin(
    plugin_id: str,
    db: IAgentDatabase = Depends(get_db),
    registry: PluginRunnerRegistry = Depends(get_plugin_registry),
):
    try:
        plugin = await db.get_plugin(plugin_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    runner = registry.get_or_create(plugin_id, db)
    if runner.is_running:
        raise HTTPException(status_code=409, detail="plugin already running")

    try:
        await runner.start(plugin.code)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return await db.get_plugin(plugin_id)


@router.post("/{plugin_id}/stop", response_model=Plugin)
async def stop_plugin(
    plugin_id: str,
    db: IAgentDatabase = Depends(get_db),
    registry: PluginRunnerRegistry = Depends(get_plugin_registry),
):
    try:
        await db.get_plugin(plugin_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    runner = registry.get(plugin_id)
    if runner is not None:
        await runner.stop()
    return await db.get_plugin(plugin_id)


@router.post("/{plugin_id}/restart", response_model=Plugin)
async def restart_plugin(
    plugin_id: str,
    db: IAgentDatabase = Depends(get_db),
    registry: PluginRunnerRegistry = Depends(get_plugin_registry),
):
    try:
        plugin = await db.get_plugin(plugin_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    runner = registry.get_or_create(plugin_id, db)
    if runner.is_running:
        await runner.stop()
    plugin = await db.get_plugin(plugin_id)
    try:
        await runner.start(plugin.code)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return await db.get_plugin(plugin_id)


@router.get("/{plugin_id}/logs")
async def get_plugin_logs(
    plugin_id: str,
    db: IAgentDatabase = Depends(get_db),
    registry: PluginRunnerRegistry = Depends(get_plugin_registry),
):
    try:
        await db.get_plugin(plugin_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    runner = registry.get(plugin_id)
    if runner is None:
        return {"lines": []}
    snapshot = runner.snapshot_logs()
    return {"lines": [l.model_dump(mode="json") for l in snapshot]}


@router.post("/{plugin_id}/logs/clear", status_code=204)
async def clear_plugin_logs(
    plugin_id: str,
    db: IAgentDatabase = Depends(get_db),
    registry: PluginRunnerRegistry = Depends(get_plugin_registry),
):
    try:
        await db.get_plugin(plugin_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    runner = registry.get(plugin_id)
    if runner is not None:
        await runner.clear_logs()


@router.websocket("/{plugin_id}/stream")
async def plugin_stream(
    plugin_id: str,
    ws: WebSocket,
    db: IAgentDatabase = Depends(get_db),
    registry: PluginRunnerRegistry = Depends(get_plugin_registry),
):
    await ws.accept()
    try:
        plugin = await db.get_plugin(plugin_id)
    except KeyError:
        await ws.send_text(json.dumps({"type": "error", "data": f"plugin '{plugin_id}' not found"}))
        await ws.close()
        return

    runner = registry.get_or_create(plugin_id, db)
    queue, snapshot, status = await runner.subscribe()

    try:
        await ws.send_text(json.dumps({
            "type": "plugin_state",
            "data": plugin.model_dump(mode="json"),
        }))
        for entry in snapshot:
            await ws.send_text(json.dumps({
                "type": "log",
                "data": entry.model_dump(mode="json"),
            }))
        await ws.send_text(json.dumps({
            "type": "status",
            "data": {"status": status.value},
        }))

        async def _client_pinger() -> None:
            # Drain client messages so disconnects are noticed promptly.
            while True:
                await ws.receive_text()

        pinger = asyncio.create_task(_client_pinger())
        try:
            while True:
                frame = await queue.get()
                await ws.send_text(json.dumps(frame))
        finally:
            pinger.cancel()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("plugin WS error plugin=%s", plugin_id)
    finally:
        await runner.unsubscribe(queue)
