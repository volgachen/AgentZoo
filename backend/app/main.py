from dotenv import load_dotenv
load_dotenv()

from app.logging_config import setup_logging
setup_logging()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import agents, sessions, fs

app = FastAPI(title="Agent Gateway", version="0.1.0")

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


@app.get("/health")
async def health():
    return {"status": "ok"}
