# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository

AgentZoo — a gateway for managing and orchestrating multiple AI agents with a real-time web dashboard. Backend is FastAPI + asyncio; frontend is React 19 + Vite + Tailwind. See `ARCHITECTURE.md` for the full design whitepaper (the validation project is an automated AI research + live-streaming workflow; roadmap includes PostgreSQL in Milestone 4). `backend/CLAUDE.md` holds backend-only notes.

## Common commands

**Backend** (run from `backend/`):
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 12598
```
API docs at `http://<host>:12598/docs`. `.env` in `backend/` is auto-loaded at startup (expects `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`, plus `MYSQL_*` + `DB_TYPE` for persistence). Type-checking config is `backend/pyrightconfig.json` (Python 3.10, scope = `app/`).

**Frontend** (run from `frontend/`):
```bash
npm install
npm run dev        # Vite dev server on :12599, host: true for LAN access
npm run build      # tsc -b && vite build
npm run lint       # eslint .
```

There is no unit-test framework. Instead, `backend/scripts/` holds standalone verification scripts (run `python scripts/<name>.py` from `backend/`, each exits 0 on success). Some need a live gateway (`uvicorn app.main:app` on :12598) and/or the `claude` CLI or `OPENAI_*` env; others use FastAPI `TestClient` + mock DB and need nothing. See `backend/scripts/README.md` for the per-script matrix. Frontend has no test suite; `npm run build` runs `tsc -b` first, so type errors fail the build.

## Architecture

### Adapter → Runner → Router layering
There are three layers, and the boundary between them is the key thing to understand:

1. **`BaseAgentAdapter`** (`adapters/base.py`) — transport-specific. Lifecycle: `start(system_prompt)` → repeated (`send(msg)` → `async for event in stream()`) → `stop()`. `stream()` must terminate each turn with a `DONE` or `ERROR` event. The adapter is **single-consumer**: only one coroutine may drive `send`/`stream`.
2. **`SessionRunner`** (`core/runner.py`) — owns exactly one adapter and is that single consumer. Everyone else is a **producer** (`submit(content, from_session_id)`) or a **subscriber** (`subscribe()`, an async context manager yielding a `StreamEvent` stream). The runner serializes turns through an inbox `asyncio.Queue` and fans every event out to all subscribers. This is what lets an HTTP-initiated turn (`POST .../messages`) show up live on every dashboard WebSocket. The runner also drives the per-turn status machine (`RUNNING` while generating → `WAITING_CONFIRM` while a tool awaits human approval → back to `RUNNING` → `WAITING_USER` on success / `ERROR` on failure) and persists messages (user input, `TOOL_CALL`/`TOOL_RESULT` rows, and the joined agent text) as it streams. `TOOL_CONFIRM` events are broadcast but not persisted.
3. **Routers** only talk to the runner, never to the adapter. `AdapterRegistry` (`adapters/registry.py`, misnamed — it now holds `SessionRunner`s) maps `session_id → SessionRunner` in memory.

When changing turn-handling, persistence-on-stream, or status transitions, edit `SessionRunner`, not the router or adapter.

### Adapter selection lives in the router
`routers/sessions.py::create_session` branches on `AgentTemplate.agent_type`, constructs the adapter, wraps it in a `SessionRunner`, starts it, and registers it:
- `CLAUDE_CODE` → `ClaudeCodeAdapter(working_dir, session_id)`
- `TOOL_USE` → `OpenAIToolUseAdapter(tool_names, model, base_url, session_id, working_dir, config)` — config comes from the `AgentTemplate` fields

To add a new agent type: add an enum value to `AgentType`, implement `BaseAgentAdapter`, and add a branch in `create_session`. Do not add transport logic to the router. `session_id` is passed at adapter **construction** (not patched in after `start`) because tools read it before the first turn.

### Claude Code adapter is per-turn, not persistent
The `claude` CLI is single-turn: each invocation reads one stdin message and exits. `ClaudeCodeAdapter` therefore spawns a fresh subprocess on every `stream()` call. Continuity is delegated to the CLI via `--session-id` (first turn) and `--resume <session_id>` (subsequent turns). Do not try to keep a long-running `claude` process — prior attempts with `asyncio.Queue` and persistent stdin failed because the CLI exits on EOF. Invoked with `--output-format stream-json --verbose`; `_parse_line` maps NDJSON events (`system/init`, `assistant`, `result`) to `StreamEvent`s.

### OpenAI tool-use adapter runs the loop internally
`OpenAIToolUseAdapter.stream()` runs the full agentic loop in-process: call chat completions → if `tool_calls` come back, execute each one and append a `role: "tool"` message → repeat until the model returns no tool calls. `TOOL_CALL` / `TOOL_RESULT` events are yielded for UI visibility and persistence; the router/runner never executes tools. Env var fallbacks apply if the `AgentTemplate` doesn't set them.

**Human-in-the-loop confirm.** Each tool's confirm policy resolves from its `BaseTool.requires_approval` class default, overridden per agent by `config.tool_approvals` (`{tool_name: bool}`). When a tool requires approval, the adapter yields a `TOOL_CONFIRM` event and blocks on an `asyncio.Future` until a human decision arrives (see WebSocket protocols). Approval runs the tool as normal; denial skips execution and feeds `"Error: user denied execution of this tool call."` back to the model as the tool result. `resolve_decision(call_id, approved)` completes the Future; `stop()` cancels any pending confirm Futures so a torn-down session doesn't leak them. Only the tool_use adapter gates — Claude Code's tools run inside the CLI subprocess with its own permission flow, so it ignores `resolve_decision`.

### Tool registry is decorator-based
Tools live in `backend/app/adapters/tools/`. Each subclasses `BaseTool` and is registered with `@register_tool`. Registration is an import side-effect: `tools/__init__.py` imports every tool module, and both `openai_tool_use.py` and `routers/tools.py` import the package. Adding a tool: create the file, subclass `BaseTool`, add `@register_tool`, then add it to `tools/__init__.py`'s import list. `AgentTemplate.tool_names: list[str]` selects which tools an agent loads. Each tool carries a `requires_approval` class attribute (its default confirm policy); `AgentTemplate.config["tool_approvals"]: dict[str, bool]` overrides that per tool for a given agent. Any tool that resolves to `True` is gated behind a `TOOL_CONFIRM`. Only the tool_use adapter honors it. `GET /api/v1/tools` returns the registered names. A tool can read `self.session_id` (set from the adapter) to act on behalf of its session.

**Tool lifecycle**: tools are instantiated once per session (in `OpenAIToolUseAdapter.start`), so instance state (e.g. `bash`'s relayed cwd, `node_repl`'s subprocess) persists across turns within a session. Stateful tools override `async def aclose()` to tear down resources; the adapter calls it in `stop()`. Tool instances do not survive a backend restart (the adapter registry is in-memory).

### Node REPL tool family
Three tools (`node_repl_js`, `node_repl_reset`, `node_repl_add_module_dir`) enable agents to bootstrap and drive codex plugins (see `codex_plugins/`). Unlike `bash` (fresh subprocess per call), these share one **persistent Node.js subprocess per session** so `globalThis` state survives across calls and turns — the codex plugins' hard requirement (they stash browser runtime under `globalThis.agent.browsers` and reuse it).

- `node_repl_js` — execute JavaScript with top-level `await`, returns `console.log` output + the snippet's completion value. Gated by default (`requires_approval=True` — arbitrary code execution, same risk class as `bash`). Descriptions mention the `mcp__node_repl__js` alias so plugin SKILL.md text resolves via tool discovery.
- `node_repl_reset` — clear user-set globals (safe, `requires_approval=False`).
- `node_repl_add_module_dir` — prepend a directory to Node's module resolution paths so `import`/`require` of bare package names resolves against it (e.g. a plugin's `scripts/node_modules`). Safe, `requires_approval=False`.

**Implementation**: `app/adapters/node_repl/server.mjs` is a newline-delimited JSON protocol server (stdin requests → stdout responses) wrapping a single shared context with async eval. `NodeReplSession` (`node_repl/registry.py`) owns the subprocess, serializes requests, and handles per-call timeout (kill+restart on hang). `NodeReplRegistry` is the in-memory `session_id → session` map; all three tools (`tools/node_repl.py`) share the same session so they operate on one context. The subprocess is spawned with `cwd=working_dir` and `start_new_session=True` (own process group for clean teardown).

**Node runtime**: set `NODE_BIN` env to override the default `node` on PATH. Missing/incompatible Node returns a clear error telling the operator to install it. The plugins ship their own `scripts/node_modules`, so no global npm install is needed once Node itself is present.

**Protocol integrity**: stdout is the NDJSON channel, so `server.mjs` hides the real `process.stdout.write` behind `reply()` and redirects all other stdout/stderr writes into the current eval's log buffer. This is not cosmetic — codex plugins retry telemetry and print warnings *asynchronously, after* the eval that started them already replied, and such a line would otherwise be read as the next request's response and desync the session permanently. `registry.py` also matches responses by request `id` (skipping unrecognized lines) and keeps stderr on its own drained pipe.

**Codex plugin host interface**: `node_repl/host_shim.mjs` installs `globalThis.nodeRepl` at process start — the one thing codex plugins require of their host (codex's own `node_repl.exe` injects it; plain `node` does not). It is installed *before* `baseKeys` is snapshotted so `node_repl_reset` won't delete it. `nodeRepl.write` / `emitContentItem` route into the eval log so plugin documentation reaches the model. `createElicitation` (the plugins' human-confirmation hook for navigation, form submit, uploads, history reads) currently auto-accepts unless `AGENTZOO_BROWSER_ELICIT=deny`; the real checkpoint is that `node_repl_js` is itself `TOOL_CONFIRM`-gated. Wiring `createElicitation` through to `TOOL_CONFIRM` properly needs a reverse channel in the protocol and is not done.

**Runtime + path discovery**: `_node_bin()` resolves `NODE_BIN` → auto-detected Codex desktop runtime (`~/AppData/Local/OpenAI/Codex/runtimes/cua_node/*/bin/node.exe`) → `node` on PATH. The desktop runtime is preferred because its bundled `node_modules` hold prebuilt natives (sharp / canvas / playwright) tied to that ABI. A `NODE_BIN` naming a nonexistent path is ignored in favor of autodetection — a quoted Windows path in `.env` gets its `\r\f\b\n` expanded by dotenv into control characters, so use forward slashes and no quotes. `codex_plugin_root()` scans `~/.codex/plugins/cache/openai-bundled/<name>/*` (preferring the `latest` alias); version dirs change on every desktop-app update, so never hardcode. On session start the plugin's `scripts/node_modules` and the runtime's `node_modules` are auto-registered, so an agent needs no `add_module_dir` call for normal browser work.

**Using codex plugins** (scope A — tool-only): the seeded **Chrome Browser Agent** (`agent-browser-chrome-001`, `db/seed_browser.py`) is the worked example. Its `system_prompt` is built at import time by `node_repl/codex_skill.py`, which inlines the installed plugin's real `skills/control-chrome/SKILL.md` behind a preamble that supplies what SKILL.md can't know: the resolved plugin root, and the fact that `mcp__node_repl__js` is `node_repl_js` here. Use `str.replace`, not `str.format`, when templating SKILL.md — it contains literal JS braces like `tabs.new({url})`. Requires the ChatGPT/Codex desktop app running with its Chrome extension connected; the plugin attaches to the backend the desktop app already established, it does not launch a browser. Interactive debugging: `python backend/scripts/test_node_repl.py`; minimal raw example in `docs/codex_chrome/`.

### Cross-session orchestration
Sessions form a tree (`Session.parent_session_id`) and can message each other, which is how multi-agent workflows are built:
- **`subagent` tool** — calls `POST /api/v1/sessions` on the gateway to spawn a child, passing the caller's id as `parent_session_id`, then sends the task as the first message. Returns immediately with the child's id (fire-and-forget). `isolation="worktree"` creates a real git worktree off the parent's working dir on branch `subagent/<id>` (falls back to an empty scratch dir under `AGENTZOO_WORKTREE_ROOT` / `backend/tmp/sessions` if the parent isn't a git repo). No `.env` is copied into the child — it inherits the backend process's environment like any other session.
- **`session_send` tool** / `POST /api/v1/sessions/{id}/messages` with `from_session_id` — queues a message into a target runner's inbox. The runner persists the raw content but prefixes the delivered text with `[from-session:<id>]` so the agent can route its reply.
- **No `.env` injection** — `create_session` never writes into a session's `working_dir` (beyond the optional `template_dir` copy). Session identity (`MY_SESSION_ID` / `PARENT_SESSION_ID`) currently has **no** delivery channel to the agent; the templates under `templates/` still document reading it from `.env` and are stale until a replacement lands.
- **Loopback HTTP must bypass proxies**: tools that call the gateway use `httpx.AsyncClient(trust_env=False)` — a system/VPN proxy would otherwise intercept the localhost request and 502.

`create_session` also supports `template_dir` (server copies it into a fresh `working_dir` before start; refuses to overwrite an existing dir).

### Repository pattern for persistence
All DB access goes through `IAgentDatabase` (abstract). Implementations: `MySqlDatabase` (`db/mysql.py`, default) and `MockMemoryDatabase` (`db/mock.py`, in-memory fallback). `DB_TYPE` in `.env` selects between them (`mysql` | `mock`). Injected via `Depends(get_db)` — the singleton in `db/deps.py`. Never import a concrete DB class from routers/adapters/tools.

The MySQL pool is opened/closed by the FastAPI `lifespan` in `app/main.py` (`init_db` / `close_db`). `MySqlDatabase.connect()` auto-creates the schema (`CREATE TABLE IF NOT EXISTS` — `agents`, `sessions`, `messages`, `plugins`, `tasks`, `task_counters`) and seeds agents (`INSERT IGNORE`) on startup, both idempotent. `aiomysql` runs `autocommit=True` (no explicit transactions); `tool_names` and `config` are JSON columns on `agents`, enums are VARCHAR. Seed `AgentTemplate`s live in `_SEED_AGENTS`, **duplicated in both `db/mysql.py` and `db/mock.py`** — update both when adding samples for a new agent type. Scripts/tests that don't go through `lifespan` never call `init_db()`; `get_db()` then lazily falls back to `MockMemoryDatabase`. `PostgreSQLDatabase` remains the Milestone 4 target.

### Task system (agent todo lists)
Ported from Claude Code's `TaskCreate/List/Get/Update` tools (originally per-task JSON files; here persisted in the DB). Four tools in `adapters/tools/task_*.py` let an agent track multi-step work: a task has `subject/description/active_form/owner/status/blocks/blocked_by/metadata`, `status ∈ pending|in_progress|completed`. Dependencies are reciprocal (`add_blocked_by` on B wires B.blocked_by += A **and** A.blocks += B in `update_task`); a blocker that is `completed` drops off the `blocked_by` view so lists auto-unblock; `delete_task` cascades to strip dangling refs. `task_update` with `status="deleted"` deletes.

**Scoping**: a task list is keyed by `task_list_id`, which **is the session id** (`_task_scope.task_list_id` falls back to `"default"` when a tool has no `session_id`). Each session owns its own list — subagents do not share the parent's. IDs are per-list monotonic integers (`"1"`, `"2"`…) from the `task_counters` table (the DB analog of Claude Code's `.highwatermark`), never reused after delete. `tasks` PK is `(task_list_id, id)`; `blocks/blocked_by/metadata` are JSON columns. The DB methods (`create_task/get_task/list_tasks/update_task/delete_task`) live on `IAgentDatabase` and are **duplicated in `db/mysql.py` + `db/mock.py`**. Read-only `GET /api/v1/sessions/{id}/tasks` (`routers/tasks.py`) exposes a list for the dashboard.

### Adapter registry is in-memory only — post-restart fallback
`AdapterRegistry` does not survive a backend restart. `routers/sessions.py::session_stream` handles this by falling through to a `_stub_loop` (echo-only) when `registry.get(session_id)` raises `KeyError`. That branch is intentional recovery, not dead code — don't remove it without replacing the strategy.

### Plugins subsystem
Independent of agents: a plugin is an arbitrary Python script the operator stores in the DB and runs as a supervised subprocess. `PluginRunner` (`plugins/runner.py`) writes the code to `backend/.plugins/<id>.py`, spawns it with `python -u` in its own process group (`start_new_session=True` so `stop()` can SIGTERM/SIGKILL the whole tree), pumps stdout/stderr into a ring `LogBuffer`, and tracks status (`STOPPED`/`RUNNING`/`EXITED`/`ERRORED`). `PluginRunnerRegistry` (`plugins/registry.py`) is the singleton map. Routes under `/api/v1/plugins` cover CRUD + `start`/`stop`/`restart`/`logs` and a `/{id}/stream` WebSocket that replays a log snapshot then streams live frames. Code edits are rejected while a plugin is `RUNNING`.

### Filesystem browser
`routers/fs.py` exposes read-only directory browsing for the dashboard's working-dir/template pickers: `/fs/browse` (free, blocks `/proc`,`/sys`,`/dev`,`/run`), `/fs/templates` (confined to the repo `templates/` root), `/fs/home`. Lists directories only, hides dotfiles.

### WebSocket protocols
- Sessions `/api/v1/sessions/{id}/stream`: on connect the server sends `{"type":"session_state","data":<Session>}`; inbound client frames are either a user turn `{"content":"<text>"}` or a tool decision `{"decision":"approve"|"deny","call_id":"<id>"}` (answering a `TOOL_CONFIRM`); outbound frames are `StreamEvent.model_dump_json()` (`{type, data}`, where `type` ∈ `user/text/tool_call/tool_confirm/tool_result/status/error/done`).
- Plugins `/api/v1/plugins/{id}/stream`: emits `plugin_state`, then `log` frames (snapshot + live), then `status`.

### Frontend
`frontend/src/api/client.ts` builds the API base URL from `window.location.hostname:12598` so the app works on any LAN host without rebuilding; Vite dev server uses `host: true` for the same reason. Do not hardcode `localhost` in fetch/WS URLs. State lives in Zustand stores (`store/sessions.ts`, `store/plugins.ts`). Pages: `AgentRegistry`, `SessionDashboard` (parent/child session tree), `LiveConsole` (per-session chat + human-in-the-loop), `PluginRegistry`, `PluginConsole`.

## Conventions

- Python 3.10+: use `X | None` union syntax.
- Pydantic v2 — use `model_dump` / `model_dump_json`, not `.dict()` / `.json()`.
- Comments in adapters/runners/tools describe *why* (e.g. subprocess-per-turn reasoning, `trust_env=False` for loopback); routers stay uncommented.
- Don't commit `backend/.env` — it holds API keys.
