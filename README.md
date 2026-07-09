# AgentZoo

A gateway for managing and orchestrating multiple AI agents, with a real-time web dashboard.

## Architecture

```
frontend/   React 19 + Vite + TypeScript + Tailwind CSS
backend/    FastAPI + asyncio
```

The backend exposes a REST + WebSocket API. Each session maps to a `SessionRunner` that owns one agent adapter instance and fans its event stream out to every dashboard subscriber. The `ClaudeCodeAdapter` drives the `claude` CLI as a subprocess per turn, using `--session-id` / `--resume` for conversation continuity; the `OpenAIToolUseAdapter` runs an in-process tool-calling loop with optional human-in-the-loop confirmation before each tool call.

## Getting Started

**Backend**

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 12598
# API available at http://<your-ip>:12598
# Docs at http://<your-ip>:12598/docs
```

**Frontend**

```bash
cd frontend
npm install
npm run dev
# Dashboard at http://<your-ip>:12599
```

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET / POST | `/api/v1/agents` | List / create agent templates |
| GET / PUT / DELETE | `/api/v1/agents/{id}` | Get, update, or delete an agent template |
| GET | `/api/v1/tools` | List registered tool names |
| POST | `/api/v1/sessions` | Create and start a session |
| GET | `/api/v1/sessions` | List sessions |
| GET | `/api/v1/sessions/{id}` | Get session status |
| GET | `/api/v1/sessions/{id}/messages` | Get message history |
| POST | `/api/v1/sessions/{id}/messages` | Send a message into a session (cross-session) |
| GET | `/api/v1/sessions/{id}/tasks` | Get the session's task list |
| DELETE | `/api/v1/sessions/{id}` | Terminate a session |
| WS | `/api/v1/sessions/{id}/stream` | Real-time event stream (duplex) |
| CRUD | `/api/v1/plugins` + `/{id}/start\|stop\|restart\|logs` | Manage supervised plugin subprocesses |
| GET | `/api/v1/fs/browse` · `/fs/templates` · `/fs/home` | Read-only filesystem browsing for pickers |

WebSocket events are JSON with `type` and `data` fields. Types: `text`, `tool_call`, `tool_confirm`, `tool_result`, `status`, `error`, `done`, `user`, `session_state`. Inbound from the client is either `{ content }` (a user turn) or `{ decision, call_id }` (approve/deny a `tool_confirm`).

## Project Structure

```
backend/app/
├── main.py              # FastAPI app entry point + lifespan (DB pool)
├── config.py            # Settings from env / .env
├── models/domain.py     # AgentTemplate, Session, Message, Task, Plugin, enums
├── core/runner.py       # SessionRunner — owns an adapter, fans out events
├── db/
│   ├── interface.py     # IAgentDatabase abstract interface
│   ├── mysql.py         # MySQL implementation (default)
│   ├── mock.py          # In-memory implementation (fallback/dev)
│   └── deps.py          # FastAPI dependency injection
├── adapters/
│   ├── base.py          # BaseAgentAdapter interface + StreamEvent types
│   ├── claude_code.py   # Claude Code CLI adapter (subprocess per turn)
│   ├── openai_tool_use.py  # OpenAI tool-calling loop + confirm gate
│   ├── registry.py      # session_id → SessionRunner registry
│   └── tools/           # Decorator-registered tools (bash, read, write, edit,
│                        #   web_search, web_fetch, subagent, session_send, task_*)
├── plugins/             # Supervised plugin subprocess runner + log buffer
└── routers/
    ├── agents.py  sessions.py  tools.py  tasks.py  fs.py  plugins.py

frontend/src/
├── api/                 # Typed fetch + WebSocket client + wire types
├── store/               # Zustand stores (sessions.ts, plugins.ts)
├── components/          # AgentDetailModal, WorkingDirPicker, TaskListPanel, SubAgentListPanel
└── pages/
    ├── AgentRegistry.tsx  SessionDashboard.tsx  LiveConsole.tsx
    └── PluginRegistry.tsx  PluginConsole.tsx
```

## Roadmap

- [x] Milestone 1 — Backend skeleton (FastAPI, mock DB, REST + WebSocket)
- [x] Milestone 2 — Claude Code adapter (subprocess, stream-json, session resume)
- [x] Milestone 3 — Frontend dashboard (Agent Registry, Session Dashboard, Live Console)
- [x] Tool-use adapter + tools, task system, plugins, MySQL persistence, human-in-the-loop tool confirm
- [ ] Milestone 4 — Research workflow + PostgreSQL
