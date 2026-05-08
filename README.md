# AgentZoo

A gateway for managing and orchestrating multiple AI agents, with a real-time web dashboard.

## Architecture

```
frontend/   React 18 + Vite + TypeScript + Tailwind CSS
backend/    FastAPI + asyncio
```

The backend exposes a REST + WebSocket API. Each session maps to one agent adapter instance. The `ClaudeCodeAdapter` drives the `claude` CLI as a subprocess per turn, using `--session-id` / `--resume` for conversation continuity.

## Getting Started

**Backend**

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
# API available at http://localhost:8000
# Docs at http://localhost:8000/docs
```

**Frontend**

```bash
cd frontend
npm install
npm run dev
# Dashboard at http://localhost:5173
```

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/agents` | List available agent templates |
| GET | `/api/v1/agents/{id}` | Get agent by ID |
| POST | `/api/v1/sessions` | Create and start a session |
| GET | `/api/v1/sessions/{id}` | Get session status |
| GET | `/api/v1/sessions/{id}/messages` | Get message history |
| DELETE | `/api/v1/sessions/{id}` | Terminate a session |
| WS | `/api/v1/sessions/{id}/stream` | Real-time event stream |

WebSocket events are JSON with `type` and `data` fields. Types: `text`, `tool_call`, `status`, `error`, `done`, `session_state`.

## Project Structure

```
backend/app/
├── main.py              # FastAPI app entry point
├── models/domain.py     # AgentTemplate, Session, Message, enums
├── db/
│   ├── interface.py     # IAgentDatabase abstract interface
│   ├── mock.py          # In-memory implementation (dev)
│   └── deps.py          # FastAPI dependency injection
├── adapters/
│   ├── base.py          # BaseAgentAdapter interface + StreamEvent types
│   ├── claude_code.py   # Claude Code CLI adapter
│   └── registry.py      # Per-session adapter registry
└── routers/
    ├── agents.py
    └── sessions.py

frontend/src/
├── api/                 # Typed fetch + WebSocket client
├── store/sessions.ts    # Zustand store for session state
└── pages/
    ├── AgentRegistry.tsx
    ├── SessionDashboard.tsx
    └── LiveConsole.tsx
```

## Roadmap

- [x] Milestone 1 — Backend skeleton (FastAPI, mock DB, REST + WebSocket)
- [x] Milestone 2 — Claude Code adapter (subprocess, stream-json, session resume)
- [x] Milestone 3 — Frontend dashboard (Agent Registry, Session Dashboard, Live Console)
- [ ] Milestone 4 — Research workflow + PostgreSQL
