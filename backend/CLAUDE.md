# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository

AgentZoo backend — a FastAPI + asyncio gateway that manages sessions over REST + WebSocket and orchestrates pluggable agent adapters (Claude Code CLI, OpenAI tool-use). The frontend lives in `../frontend/`; the full-system design is in `../ARCHITECTURE.md`.

## Common commands

Run from this directory (`backend/`):

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 12598
```

API docs at `http://<host>:12598/docs`. `.env` in this directory is auto-loaded at startup (expects `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`, plus `MYSQL_*` + `DB_TYPE` for persistence — see the persistence section).

Type-checking uses `pyrightconfig.json` (Python 3.10, scope = `app/`). There is no test suite yet.

## Architecture

### One gateway session = one adapter instance
Each `Session` in the DB is paired with a live `BaseAgentAdapter`, driven by a `SessionRunner` (see below) and registered in `AdapterRegistry` (in-memory, singleton via `get_registry()` — despite the name it now holds `SessionRunner`s, not raw adapters). The adapter encapsulates everything transport-specific; the router layer only knows the `StreamEvent` protocol (`TEXT` / `TOOL_CALL` / `TOOL_CONFIRM` / `TOOL_RESULT` / `STATUS` / `ERROR` / `DONE`).

Adapter lifecycle: `start(system_prompt)` → repeated (`send(msg)` → `async for event in stream()`) → `stop()`. `stream()` must terminate each turn with a `DONE` or `ERROR` event; the router uses this to know when to return control to the WebSocket loop.

### Adapter selection lives in the router
`routers/sessions.py` builds the adapter in the `_build_runner` helper (shared by `create_session` and the post-restart rehydration path), branching on `AgentTemplate.agent_type`:
- `CLAUDE_CODE` → `ClaudeCodeAdapter(working_dir=…, session_id=…)`
- `TOOL_USE` → `OpenAIToolUseAdapter(tool_names, model, base_url, session_id, working_dir, config)` — config comes from the `AgentTemplate` fields

To add a new agent type: add an enum value to `AgentType`, implement `BaseAgentAdapter`, and add a branch in `_build_runner`. Do not add transport logic to the router.

### Claude Code adapter is per-turn, not persistent
The `claude` CLI is single-turn: each invocation reads one stdin message and exits. `ClaudeCodeAdapter` therefore spawns a fresh subprocess on every `stream()` call. Continuity is delegated to the CLI itself via `--session-id` (first turn) and `--resume <session_id>` (subsequent turns). Do not try to keep a long-running `claude` process — prior attempts with `asyncio.Queue` and persistent stdin failed because the CLI exits on EOF.

The CLI is invoked with `--output-format stream-json --verbose`; `_parse_line` maps NDJSON events (`system/init`, `assistant`, `result`) to `StreamEvent`s.

### OpenAI tool-use adapter runs the loop internally
`OpenAIToolUseAdapter.stream()` runs the full agentic loop in-process: call chat completions → if `tool_calls` come back, execute each one and append a `role: "tool"` message → repeat until the model returns no tool calls. `TOOL_CALL` and `TOOL_RESULT` events are yielded for UI visibility (and persisted by the runner); the router never needs to handle tool execution.

Whether a tool needs a human confirm is resolved per tool: each tool declares a class-level `BaseTool.requires_approval` default (safe default `True`; low-risk tools — `read`, `web_search`, `web_fetch`, `arxiv_search`, `list_subagents`, `task_*` — set it `False`), and the agent's `config.tool_approvals` (`{tool_name: requires_approval}`) overrides that default per tool. When a tool resolves to "requires approval", the adapter yields a `TOOL_CONFIRM` event and blocks on an `asyncio.Future` until a human approves/denies (routed in via `resolve_decision(call_id, approved)`). Denial skips execution and returns `"Error: user denied execution of this tool call."` to the model; `stop()` cancels any pending confirm Futures. Claude Code ignores this — its tools run in the CLI subprocess under the CLI's own permission flow.

Env var fallbacks apply if the `AgentTemplate` doesn't set them: `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`.

### Tool registry is decorator-based
Tools live in `app/adapters/tools/`. Each tool subclasses `BaseTool` and is registered with `@register_tool`. Registration happens as an import side-effect: `tools/__init__.py` imports every tool module, and `openai_tool_use.py` imports the `tools` package. Adding a new tool is: create the file, subclass `BaseTool`, add `@register_tool`, then add it to `tools/__init__.py`'s import list. `AgentTemplate.tool_names: list[str]` controls which tools are loaded for a given agent. Each tool's confirm policy comes from its `requires_approval` class attribute, overridable per agent via `AgentTemplate.config["tool_approvals"]: dict[str, bool]` (tool_use adapter only).

**Tool lifecycle**: tools are instantiated once per session (in `OpenAIToolUseAdapter.start`), so instance state (e.g. `bash`'s relayed cwd, `node_repl`'s subprocess) persists across turns within a session. Stateful tools override `async def aclose()` to tear down resources; the adapter calls it in `stop()`. Tool instances do not survive a backend restart (the adapter registry is in-memory).

### Node REPL tool family
Three tools (`node_repl_js`, `node_repl_reset`, `node_repl_add_module_dir`) enable agents to bootstrap and drive codex plugins (see `../../codex_plugins/`). Unlike `bash` (fresh subprocess per call), these share one **persistent Node.js subprocess per session** so `globalThis` state survives across calls and turns — the codex plugins' hard requirement (they stash browser runtime under `globalThis.agent.browsers` and reuse it).

- `node_repl_js` — execute JavaScript with top-level `await`, returns `console.log` output + the snippet's completion value. Gated by default (`requires_approval=True` — arbitrary code execution, same risk class as `bash`). Descriptions mention the `mcp__node_repl__js` alias so plugin SKILL.md text resolves via tool discovery.
- `node_repl_reset` — clear user-set globals (safe, `requires_approval=False`).
- `node_repl_add_module_dir` — prepend a directory to Node's module resolution paths so `import`/`require` of bare package names resolves against it (e.g. a plugin's `scripts/node_modules`). Safe, `requires_approval=False`.

**Implementation**: `app/adapters/node_repl/server.mjs` is a newline-delimited JSON protocol server (stdin requests → stdout responses) wrapping a single shared context with async eval. `NodeReplSession` (`node_repl/registry.py`) owns the subprocess, serializes requests, and handles per-call timeout (kill+restart on hang). `NodeReplRegistry` is the in-memory `session_id → session` map; all three tools (`tools/node_repl.py`) share the same session so they operate on one context. The subprocess is spawned with `cwd=working_dir` and `start_new_session=True` (own process group for clean teardown).

**Node runtime**: set `NODE_BIN` env to override the default `node` on PATH. Missing/incompatible Node returns a clear error telling the operator to install it. The plugins ship their own `scripts/node_modules`, so no global npm install is needed once Node itself is present.

**Using codex plugins** (scope A — tool-only): add the three `node_repl_*` tools to an agent's `tool_names`, paste the plugin's `SKILL.md` into that agent's `system_prompt` (with the absolute plugin root path resolved), and optionally drop `node_repl_js` from `tool_approvals` if you trust the session. The agent then imports the plugin's `scripts/browser-client.mjs` and calls `setupBrowserRuntime({ globals: globalThis })` to bootstrap. Interactive debugging: `python scripts/test_node_repl.py`.

### Repository pattern for persistence
All DB access goes through `IAgentDatabase` (abstract). Two implementations exist: `MySqlDatabase` (`db/mysql.py`, default) and `MockMemoryDatabase` (`db/mock.py`, in-memory fallback). `DB_TYPE` in `.env` selects between them (`mysql` | `mock`). Injected via `Depends(get_db)` — the singleton in `db/deps.py`. Never import a concrete DB class directly from routers or adapters.

The MySQL pool is opened/closed by the FastAPI `lifespan` in `app/main.py` (`init_db` / `close_db` in `db/deps.py`). `MySqlDatabase.connect()` auto-creates the schema (`CREATE TABLE IF NOT EXISTS` — 6 tables: `agents`, `sessions`, `messages`, `plugins`, `tasks`, `task_counters`) and seeds agents (`INSERT IGNORE`) on startup, so both are idempotent; the resulting "table already exists" / "duplicate entry" warnings are suppressed via `warnings.catch_warnings()`. Connection settings come from `MYSQL_HOST/PORT/USER/PASSWORD/DATABASE` via `app/config.py::get_settings`. `aiomysql` runs with `autocommit=True` (no explicit transactions); `tool_names` and `config` are stored as JSON columns on `agents`, enums as VARCHAR. Seed `AgentTemplate`s live in `_SEED_AGENTS` (duplicated in both `db/mysql.py` and `db/mock.py`) — update both when introducing a new agent type. `PostgreSQLDatabase` remains the Milestone 4 target.

### Task system (agent todo lists)
`task_create/task_list/task_get/task_update` (`adapters/tools/task_*.py`) give agents a todo list, ported from Claude Code's Task tools but persisted in the DB (`tasks` + `task_counters` tables) rather than JSON files. A task list is keyed by `task_list_id` = the caller's `session_id` (`_task_scope.task_list_id`, fallback `"default"`); ids are per-list monotonic integers from `task_counters`, never reused. Dependencies are reciprocal and `completed` blockers auto-drop; `delete_task` cascades. DB methods live on `IAgentDatabase` (duplicated in `mysql.py` + `mock.py`). Read-only `GET /sessions/{id}/tasks` in `routers/tasks.py`.

Scripts/tests that don't go through the app `lifespan` never call `init_db()`; `get_db()` then lazily falls back to `MockMemoryDatabase`, so they keep working without a live MySQL.

### Adapter registry is in-memory only
`AdapterRegistry` maps `session_id → SessionRunner` in a dict; it does not survive a backend restart. `routers/sessions.py::session_stream` handles the post-restart case by first attempting `_get_or_rehydrate` (which rebuilds a tool_use runner from persisted DB state) and only falling through to a `[stub]` echo loop when rehydration returns `None`. That stub branch is intentional recovery, not dead code — don't remove it without replacing the strategy.

### WebSocket protocol
`/api/v1/sessions/{id}/stream` is the one duplex channel. On connect, the server sends `{"type": "session_state", "data": <Session>}`. Inbound messages from the client are JSON — either a user turn `{"content": "<user text>"}` or a tool decision `{"decision": "approve"|"deny", "call_id": "<id>"}` answering a `TOOL_CONFIRM`. Outbound messages are `StreamEvent.model_dump_json()` (same `{type, data}` shape; `type` ∈ `user/text/tool_call/tool_confirm/tool_result/status/error/done`).

## Conventions

- Python 3.10+: use `X | None` union syntax.
- Pydantic v2 — use `model_dump` / `model_dump_json`, not `.dict()` / `.json()`.
- Comments in adapters describe *why* (e.g. subprocess-per-turn reasoning); routers and tools stay uncommented.
- Don't commit `.env` — it holds API keys.
