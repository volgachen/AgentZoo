from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from app.logging_config import setup_logging
setup_logging()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.deps import get_db, init_db, close_db
from app.plugins.catalog import get_plugin_catalog
from app.plugins.events import get_plugin_event_bus
from app.plugins.registry import get_plugin_registry
from app.plugins.service import (
    auto_start_plugin_instances,
    recover_interrupted_plugin_runs,
    register_plugin_event_delivery,
    stop_running_plugin_instances,
)
from app.routers import agents, sessions, fs, plugins, tools, tasks


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    db = get_db()
    registry = get_plugin_registry()
    catalog = get_plugin_catalog()
    event_bus = get_plugin_event_bus()
    register_plugin_event_delivery(event_bus, db, registry, catalog)
    await recover_interrupted_plugin_runs(db)
    # await auto_start_plugin_instances(db, registry, catalog)
    try:
        yield
    finally:
        await stop_running_plugin_instances(db, registry)
        await close_db()


app = FastAPI(title="Agent Gateway", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(fs.router, prefix="/api/v1")
app.include_router(plugins.router, prefix="/api/v1")
app.include_router(tools.router, prefix="/api/v1")
app.include_router(tasks.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
