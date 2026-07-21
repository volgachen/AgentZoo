# Database Structure

AgentZoo persists all state through the `IAgentDatabase` interface (`app/db/interface.py`). The canonical schema lives in `app/db/mysql.py` (`_SCHEMA_SQL`); `MockMemoryDatabase` (`app/db/mock.py`) mirrors the same shapes in memory. `DB_TYPE` (`mysql` | `mock`) in `.env` selects the implementation.

The MySQL schema is auto-created idempotently (`CREATE TABLE IF NOT EXISTS`) on startup via the FastAPI `lifespan` → `MySqlDatabase.connect()`. Six tables:

## `agents`
Agent templates (seed data + operator-created).

| Column | Type | Notes |
|---|---|---|
| `id` | VARCHAR(36) | PK |
| `name` | VARCHAR(200) | NOT NULL |
| `description` | TEXT | NOT NULL |
| `agent_type` | VARCHAR(50) | enum-as-string (`claude_code` \| `tool_use`) |
| `system_prompt` | TEXT | NOT NULL |
| `tool_names` | JSON | NOT NULL — tools the agent loads |
| `config` | JSON | nullable — per-agent config bag; `config.tool_approvals` = `{tool: requires_approval}` overrides of each tool's default |
| `openai_model` | VARCHAR(100) | default `'gpt-4o'` |
| `openai_base_url` | VARCHAR(500) | nullable |
| `created_at` | DATETIME(3) | NOT NULL |

## `sessions`
Live/past sessions; form a tree via `parent_session_id`.

| Column | Type | Notes |
|---|---|---|
| `id` | VARCHAR(36) | PK |
| `agent_id` | VARCHAR(36) | NOT NULL |
| `working_dir` | VARCHAR(1000) | nullable |
| `parent_session_id` | VARCHAR(36) | nullable |
| `additional_prompt` | LONGTEXT | nullable |
| `additional_prompt_path` | VARCHAR(1000) | nullable |
| `status` | VARCHAR(30) | default `'INITIALIZING'` |
| `created_at` | DATETIME(3) | NOT NULL |
| `updated_at` | DATETIME(3) | NOT NULL |

Indexes: `idx_sessions_agent (agent_id)`, `idx_sessions_parent (parent_session_id)`.

## `messages`
Turn history (user input, `TOOL_CALL`/`TOOL_RESULT` rows, joined agent text).

| Column | Type | Notes |
|---|---|---|
| `id` | VARCHAR(36) | PK |
| `session_id` | VARCHAR(36) | NOT NULL |
| `role` | VARCHAR(20) | NOT NULL |
| `content` | LONGTEXT | NOT NULL |
| `from_session_id` | VARCHAR(36) | nullable — set for cross-session messages |
| `created_at` | DATETIME(3) | NOT NULL |

Index: `idx_messages_session (session_id)`. FK: `session_id → sessions(id) ON DELETE CASCADE`.

## `plugins`
Operator-stored Python scripts run as supervised subprocesses.

| Column | Type | Notes |
|---|---|---|
| `id` | VARCHAR(36) | PK |
| `name` | VARCHAR(200) | NOT NULL |
| `code` | LONGTEXT | NOT NULL |
| `status` | VARCHAR(30) | default `'stopped'` |
| `last_started_at` | DATETIME(3) | nullable |
| `last_exited_at` | DATETIME(3) | nullable |
| `last_exit_code` | INT | nullable |
| `last_error` | TEXT | nullable |
| `created_at` | DATETIME(3) | NOT NULL |
| `updated_at` | DATETIME(3) | NOT NULL |

## `tasks`
Agent todo lists. Keyed by `task_list_id` (= the owning session id); ids are per-list monotonic integers.

| Column | Type | Notes |
|---|---|---|
| `task_list_id` | VARCHAR(64) | PK part |
| `id` | VARCHAR(20) | PK part — per-list integer as string |
| `subject` | TEXT | NOT NULL |
| `description` | LONGTEXT | NOT NULL |
| `active_form` | VARCHAR(500) | nullable |
| `owner` | VARCHAR(200) | nullable |
| `status` | VARCHAR(20) | default `'pending'` (`pending`\|`in_progress`\|`completed`) |
| `blocks` | JSON | NOT NULL — reciprocal dependency refs |
| `blocked_by` | JSON | NOT NULL — reciprocal dependency refs |
| `metadata` | JSON | nullable |
| `created_at` | DATETIME(3) | NOT NULL |
| `updated_at` | DATETIME(3) | NOT NULL |

PK: `(task_list_id, id)`. Index: `idx_tasks_list (task_list_id)`.

## `task_counters`
Per-list monotonic id allocator (DB analog of Claude Code's `.highwatermark`).

| Column | Type | Notes |
|---|---|---|
| `task_list_id` | VARCHAR(64) | PK |
| `next_id` | BIGINT | NOT NULL |

## Conventions
- Engine `InnoDB`, charset `utf8mb4` on every table.
- `aiomysql` runs `autocommit=True` (no explicit transactions).
- Enums stored as VARCHAR; list/dict fields stored as JSON columns.
- Agents are seeded via `INSERT IGNORE` from `_SEED_AGENTS`, duplicated in both `db/mysql.py` and `db/mock.py`.
- `PostgreSQLDatabase` remains the Milestone 4 target.
