import json
import warnings
from datetime import datetime, timezone
from typing import Any

import aiomysql
from aiomysql import DictCursor, Pool

from app.config import Settings
from app.db.interface import IAgentDatabase, _UNSET
from app.models.domain import (
    AgentTemplate,
    AgentType,
    Message,
    MessageRole,
    Plugin,
    PluginStatus,
    Session,
    SessionStatus,
    Task,
    TaskStatus,
)

_SCHEMA_SQL = [
    """\
CREATE TABLE IF NOT EXISTS agents (
    id             VARCHAR(36)   PRIMARY KEY,
    name           VARCHAR(200)  NOT NULL,
    description    TEXT          NOT NULL,
    agent_type     VARCHAR(50)   NOT NULL,
    system_prompt  TEXT          NOT NULL,
    tool_names     JSON          NOT NULL,
    openai_model   VARCHAR(100)  NOT NULL DEFAULT 'gpt-4o',
    openai_base_url VARCHAR(500) DEFAULT NULL,
    created_at     DATETIME(3)   NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """\
CREATE TABLE IF NOT EXISTS sessions (
    id                VARCHAR(36)   PRIMARY KEY,
    agent_id          VARCHAR(36)   NOT NULL,
    working_dir       VARCHAR(1000) DEFAULT NULL,
    parent_session_id VARCHAR(36)   DEFAULT NULL,
    status            VARCHAR(30)   NOT NULL DEFAULT 'INITIALIZING',
    created_at        DATETIME(3)   NOT NULL,
    updated_at        DATETIME(3)   NOT NULL,
    INDEX idx_sessions_agent (agent_id),
    INDEX idx_sessions_parent (parent_session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """\
CREATE TABLE IF NOT EXISTS messages (
    id               VARCHAR(36)  PRIMARY KEY,
    session_id       VARCHAR(36)  NOT NULL,
    role             VARCHAR(20)  NOT NULL,
    content          LONGTEXT     NOT NULL,
    from_session_id  VARCHAR(36)  DEFAULT NULL,
    created_at       DATETIME(3)  NOT NULL,
    INDEX idx_messages_session (session_id),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """\
CREATE TABLE IF NOT EXISTS plugins (
    id              VARCHAR(36)  PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    code            LONGTEXT     NOT NULL,
    status          VARCHAR(30)  NOT NULL DEFAULT 'stopped',
    last_started_at DATETIME(3)  DEFAULT NULL,
    last_exited_at  DATETIME(3)  DEFAULT NULL,
    last_exit_code  INT          DEFAULT NULL,
    last_error      TEXT         DEFAULT NULL,
    created_at      DATETIME(3)  NOT NULL,
    updated_at      DATETIME(3)  NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """\
CREATE TABLE IF NOT EXISTS tasks (
    task_list_id  VARCHAR(64)  NOT NULL,
    id            VARCHAR(20)  NOT NULL,
    subject       TEXT         NOT NULL,
    description   LONGTEXT     NOT NULL,
    active_form   VARCHAR(500) DEFAULT NULL,
    owner         VARCHAR(200) DEFAULT NULL,
    status        VARCHAR(20)  NOT NULL DEFAULT 'pending',
    blocks        JSON         NOT NULL,
    blocked_by    JSON         NOT NULL,
    metadata      JSON         DEFAULT NULL,
    created_at    DATETIME(3)  NOT NULL,
    updated_at    DATETIME(3)  NOT NULL,
    PRIMARY KEY (task_list_id, id),
    INDEX idx_tasks_list (task_list_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """\
CREATE TABLE IF NOT EXISTS task_counters (
    task_list_id  VARCHAR(64)  PRIMARY KEY,
    next_id       BIGINT       NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]

_SEED_AGENTS: list[dict[str, Any]] = [
    {
        "id": "main-agent",
        "name": "Main Agent",
        "description": "一个通用的智能体，配备了多种工具，能够处理各种任务。",
        "agent_type": "tool_use",
        "system_prompt": (
            "You are a information searcher specialized in gathering, vetting, and synthesizing "
            "information from the web. Your job is to find high-quality sources and deliver "
            "actionable research reports.\n\n"
            "## Core workflow\n"
            "1. **Understand the request** — clarify scope, time constraints, and required "
            "depth before searching. If anything is ambiguous, ask before proceeding.\n"
            "2. **Search broadly** — use web_search to cast a wide net. Run multiple "
            "searches with different angles and keywords. Prefer authoritative domains "
            "(.edu, .gov, official docs, reputable publications).\n"
            "3. **Read deeply** — use web_fetch on the most promising results. Never "
            "summarize from search snippets alone — always read the source.\n"
            "4. **Cross-verify** — key claims should be confirmed by at least 2 "
            "independent sources. Flag contradictions or outlier claims explicitly.\n"
            "5. **Record** — use write to save your findings as a structured markdown "
            "file. Use edit to refine and update your notes as new information "
            "comes in. Use read to review previously saved materials.\n"
            "6. **Deliver** — Deliver the results as required. If the task requires to save the information, just do it following the required file struture and format. "
            "If the task requires a feedback report, send your report to the requesting session via session_send.\n\n"
            "## Rules\n"
            "- Never fabricate URLs or cite a source you haven't fetched.\n"
            "- When web_fetch fails, report it — don't guess what was on the page.\n"
            "- If you find contradictory information, present both sides.\n"
            "- Structure long reports with clear headings for readability."
        ),
        "tool_names": [
            "web_search", "web_fetch", "arxiv_search",
            "session_send", "write", "read", "edit",
        ],
        "openai_model": "gpt-5.4",
        "openai_base_url": None,
    },
    {
        "id": "information_searcher",
        "name": "Information Searcher",
        "description": "通过网络搜索、论文检索、网页抓取等工具搜集资料，整理为结构化研究报告。",
        "agent_type": "tool_use",
        "system_prompt": (
            "You are a information searcher specialized in gathering, vetting, and synthesizing "
            "information from the web. Your job is to find high-quality sources and deliver "
            "actionable research reports.\n\n"
            "## Core workflow\n"
            "1. **Understand the request** — clarify scope, time constraints, and required "
            "depth before searching. If anything is ambiguous, ask before proceeding.\n"
            "2. **Search broadly** — use web_search to cast a wide net. Run multiple "
            "searches with different angles and keywords. Prefer authoritative domains "
            "(.edu, .gov, official docs, reputable publications).\n"
            "3. **Read deeply** — use web_fetch on the most promising results. Never "
            "summarize from search snippets alone — always read the source.\n"
            "4. **Cross-verify** — key claims should be confirmed by at least 2 "
            "independent sources. Flag contradictions or outlier claims explicitly.\n"
            "5. **Record** — use write to save your findings as a structured markdown "
            "file. Use edit to refine and update your notes as new information "
            "comes in. Use read to review previously saved materials.\n"
            "6. **Deliver** — Deliver the results as required. If the task requires to save the information, just do it following the required file struture and format. "
            "If the task requires a feedback report, send your report to the requesting session via session_send.\n\n"
            "## Rules\n"
            "- Never fabricate URLs or cite a source you haven't fetched.\n"
            "- When web_fetch fails, report it — don't guess what was on the page.\n"
            "- If you find contradictory information, present both sides.\n"
            "- Structure long reports with clear headings for readability."
        ),
        "tool_names": [
            "web_search", "web_fetch", "arxiv_search",
            "session_send", "write", "read", "edit",
        ],
        "openai_model": "gpt-5.4",
        "openai_base_url": None,
    },
    {
        "id": "agent-claude-code-001",
        "name": "Claude Code Agent",
        "description": "驱动 Claude Code CLI 完成复杂编程与脚本生成任务。",
        "agent_type": "claude_code",
        "system_prompt": "You are a coding assistant powered by Claude Code.",
        "tool_names": [],
        "openai_model": "claude-sonnet",
        "openai_base_url": None,
    },
]


def _row_to_agent(row: dict[str, Any]) -> AgentTemplate:
    tool_names = row["tool_names"]
    if isinstance(tool_names, str):
        tool_names = json.loads(tool_names)
    return AgentTemplate(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        agent_type=AgentType(row["agent_type"]),
        system_prompt=row["system_prompt"],
        tool_names=tool_names,
        openai_model=row["openai_model"],
        openai_base_url=row["openai_base_url"],
        created_at=row["created_at"],
    )


def _row_to_session(row: dict[str, Any]) -> Session:
    return Session(
        id=row["id"],
        agent_id=row["agent_id"],
        working_dir=row["working_dir"],
        parent_session_id=row["parent_session_id"],
        status=SessionStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_message(row: dict[str, Any]) -> Message:
    return Message(
        id=row["id"],
        session_id=row["session_id"],
        role=MessageRole(row["role"]),
        content=row["content"],
        from_session_id=row["from_session_id"],
        created_at=row["created_at"],
    )


def _row_to_plugin(row: dict[str, Any]) -> Plugin:
    return Plugin(
        id=row["id"],
        name=row["name"],
        code=row["code"],
        status=PluginStatus(row["status"]),
        last_started_at=row["last_started_at"],
        last_exited_at=row["last_exited_at"],
        last_exit_code=row["last_exit_code"],
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _json_col(value: Any, default: Any) -> Any:
    # JSON columns come back as already-decoded objects on some aiomysql/MySQL
    # versions and as raw strings on others; normalize both.
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


def _row_to_task(row: dict[str, Any]) -> Task:
    return Task(
        id=row["id"],
        task_list_id=row["task_list_id"],
        subject=row["subject"],
        description=row["description"],
        active_form=row["active_form"],
        owner=row["owner"],
        status=TaskStatus(row["status"]),
        blocks=_json_col(row["blocks"], []),
        blocked_by=_json_col(row["blocked_by"], []),
        metadata=_json_col(row["metadata"], None),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class MySqlDatabase(IAgentDatabase):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: Pool | None = None

    async def connect(self) -> None:
        self._pool = await aiomysql.create_pool(
            host=self._settings.mysql_host,
            port=self._settings.mysql_port,
            user=self._settings.mysql_user,
            password=self._settings.mysql_password,
            db=self._settings.mysql_database,
            minsize=2,
            maxsize=10,
            autocommit=True,
        )
        await self._init_schema()
        await self._seed_agents()

    async def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None

    async def _init_schema(self) -> None:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    for sql in _SCHEMA_SQL:
                        await cur.execute(sql)

    async def _seed_agents(self) -> None:
        now = datetime.now(timezone.utc)
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    for agent in _SEED_AGENTS:
                        await cur.execute(
                        """INSERT IGNORE INTO agents
                           (id, name, description, agent_type, system_prompt,
                            tool_names, openai_model, openai_base_url, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            agent["id"],
                            agent["name"],
                            agent["description"],
                            agent["agent_type"],
                            agent["system_prompt"],
                            json.dumps(agent["tool_names"]),
                            agent["openai_model"],
                            agent["openai_base_url"],
                            now,
                        ),
                    )

    # ---- Agents ----

    async def list_agents(self) -> list[AgentTemplate]:
        async with self._pool.acquire() as conn:
            async with conn.cursor(DictCursor) as cur:
                await cur.execute("SELECT * FROM agents ORDER BY created_at")
                rows = await cur.fetchall()
        return [_row_to_agent(r) for r in rows]

    async def get_agent(self, agent_id: str) -> AgentTemplate:
        async with self._pool.acquire() as conn:
            async with conn.cursor(DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM agents WHERE id = %s", (agent_id,)
                )
                row = await cur.fetchone()
        if row is None:
            raise KeyError(f"Agent '{agent_id}' not found")
        return _row_to_agent(row)

    async def create_agent(self, template: AgentTemplate) -> AgentTemplate:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO agents
                       (id, name, description, agent_type, system_prompt,
                        tool_names, openai_model, openai_base_url, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        template.id,
                        template.name,
                        template.description,
                        template.agent_type.value,
                        template.system_prompt,
                        json.dumps(template.tool_names),
                        template.openai_model,
                        template.openai_base_url,
                        template.created_at,
                    ),
                )
        return template

    async def update_agent(
        self,
        agent_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        system_prompt: str | None = None,
        tool_names: list[str] | None = None,
        openai_model: str | None = None,
        openai_base_url: str | None = None,
    ) -> AgentTemplate:
        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name
        if description is not None:
            updates["description"] = description
        if system_prompt is not None:
            updates["system_prompt"] = system_prompt
        if tool_names is not None:
            updates["tool_names"] = json.dumps(tool_names)
        if openai_model is not None:
            updates["openai_model"] = openai_model
        if openai_base_url is not None:
            updates["openai_base_url"] = openai_base_url

        if not updates:
            return await self.get_agent(agent_id)

        set_clause = ", ".join(f"{k} = %s" for k in updates)
        values = list(updates.values()) + [agent_id]

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"UPDATE agents SET {set_clause} WHERE id = %s",
                    values,
                )
        return await self.get_agent(agent_id)

    async def delete_agent(self, agent_id: str) -> None:
        await self.get_agent(agent_id)
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM agents WHERE id = %s", (agent_id,))

    # ---- Sessions ----

    async def create_session(
        self,
        agent_id: str,
        working_dir: str | None = None,
        *,
        parent_session_id: str | None = None,
    ) -> Session:
        await self.get_agent(agent_id)
        session = Session(
            agent_id=agent_id,
            working_dir=working_dir,
            parent_session_id=parent_session_id,
        )
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO sessions
                       (id, agent_id, working_dir, parent_session_id,
                        status, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        session.id,
                        session.agent_id,
                        session.working_dir,
                        session.parent_session_id,
                        session.status.value,
                        session.created_at,
                        session.updated_at,
                    ),
                )
        return session

    async def get_session(self, session_id: str) -> Session:
        async with self._pool.acquire() as conn:
            async with conn.cursor(DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM sessions WHERE id = %s", (session_id,)
                )
                row = await cur.fetchone()
        if row is None:
            raise KeyError(f"Session '{session_id}' not found")
        return _row_to_session(row)

    async def list_sessions(self) -> list[Session]:
        async with self._pool.acquire() as conn:
            async with conn.cursor(DictCursor) as cur:
                await cur.execute("SELECT * FROM sessions ORDER BY created_at")
                rows = await cur.fetchall()
        return [_row_to_session(r) for r in rows]

    async def update_session_status(
        self, session_id: str, status: SessionStatus
    ) -> Session:
        now = datetime.now(timezone.utc)
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                result = await cur.execute(
                    """UPDATE sessions SET status = %s, updated_at = %s
                       WHERE id = %s""",
                    (status.value, now, session_id),
                )
        if result == 0:
            raise KeyError(f"Session '{session_id}' not found")
        return await self.get_session(session_id)

    # ---- Messages ----

    async def add_message(
        self,
        session_id: str,
        role: MessageRole,
        content: str,
        *,
        from_session_id: str | None = None,
    ) -> Message:
        await self.get_session(session_id)
        message = Message(
            session_id=session_id,
            role=role,
            content=content,
            from_session_id=from_session_id,
        )
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO messages
                       (id, session_id, role, content, from_session_id, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        message.id,
                        message.session_id,
                        message.role.value,
                        message.content,
                        message.from_session_id,
                        message.created_at,
                    ),
                )
        return message

    async def get_messages(self, session_id: str) -> list[Message]:
        await self.get_session(session_id)
        async with self._pool.acquire() as conn:
            async with conn.cursor(DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM messages WHERE session_id = %s ORDER BY created_at",
                    (session_id,),
                )
                rows = await cur.fetchall()
        return [_row_to_message(r) for r in rows]

    # ---- Plugins ----

    async def list_plugins(self) -> list[Plugin]:
        async with self._pool.acquire() as conn:
            async with conn.cursor(DictCursor) as cur:
                await cur.execute("SELECT * FROM plugins ORDER BY created_at")
                rows = await cur.fetchall()
        return [_row_to_plugin(r) for r in rows]

    async def get_plugin(self, plugin_id: str) -> Plugin:
        async with self._pool.acquire() as conn:
            async with conn.cursor(DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM plugins WHERE id = %s", (plugin_id,)
                )
                row = await cur.fetchone()
        if row is None:
            raise KeyError(f"Plugin '{plugin_id}' not found")
        return _row_to_plugin(row)

    async def create_plugin(self, name: str, code: str) -> Plugin:
        plugin = Plugin(name=name, code=code)
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO plugins
                       (id, name, code, status, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        plugin.id,
                        plugin.name,
                        plugin.code,
                        plugin.status.value,
                        plugin.created_at,
                        plugin.updated_at,
                    ),
                )
        return plugin

    async def update_plugin(
        self,
        plugin_id: str,
        *,
        name: str | None = None,
        code: str | None = None,
    ) -> Plugin:
        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name
        if code is not None:
            updates["code"] = code

        if not updates:
            return await self.get_plugin(plugin_id)

        updates["updated_at"] = datetime.now(timezone.utc)
        set_clause = ", ".join(f"{k} = %s" for k in updates)
        values = list(updates.values()) + [plugin_id]

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"UPDATE plugins SET {set_clause} WHERE id = %s",
                    values,
                )
        return await self.get_plugin(plugin_id)

    async def delete_plugin(self, plugin_id: str) -> None:
        await self.get_plugin(plugin_id)
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM plugins WHERE id = %s", (plugin_id,))

    async def set_plugin_status(
        self,
        plugin_id: str,
        status: PluginStatus,
        *,
        exit_code: int | None = None,
        error: str | None = None,
    ) -> Plugin:
        now = datetime.now(timezone.utc)
        updates: dict[str, Any] = {"status": status.value, "updated_at": now}

        if status == PluginStatus.RUNNING:
            updates["last_started_at"] = now
            updates["last_exited_at"] = None
            updates["last_exit_code"] = None
            updates["last_error"] = None
        else:
            updates["last_exited_at"] = now
            if exit_code is not None:
                updates["last_exit_code"] = exit_code
            if error is not None:
                updates["last_error"] = error

        set_clause = ", ".join(f"{k} = %s" for k in updates)
        values = list(updates.values()) + [plugin_id]

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"UPDATE plugins SET {set_clause} WHERE id = %s",
                    values,
                )
        return await self.get_plugin(plugin_id)

    # ---- Tasks ----

    async def _next_task_id(self, task_list_id: str) -> int:

        # Atomic per-list counter via the LAST_INSERT_ID upsert trick: the INSERT
        # seeds next_id=1, the ON DUPLICATE path bumps it; both stash the value in
        # the connection's LAST_INSERT_ID() so a single follow-up SELECT reads it.
        # Counter survives deletes, so ids are monotonic and never reused.
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO task_counters (task_list_id, next_id)
                       VALUES (%s, LAST_INSERT_ID(1))
                       ON DUPLICATE KEY UPDATE next_id = LAST_INSERT_ID(next_id + 1)""",
                    (task_list_id,),
                )
                await cur.execute("SELECT LAST_INSERT_ID()")
                row = await cur.fetchone()
        return int(row[0])

    async def create_task(
        self,
        task_list_id: str,
        subject: str,
        description: str,
        *,
        active_form: str | None = None,
        metadata: dict | None = None,
    ) -> Task:
        next_id = await self._next_task_id(task_list_id)
        task = Task(
            id=str(next_id),
            task_list_id=task_list_id,
            subject=subject,
            description=description,
            active_form=active_form,
            metadata=metadata,
        )
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO tasks
                       (task_list_id, id, subject, description, active_form,
                        owner, status, blocks, blocked_by, metadata,
                        created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        task.task_list_id,
                        task.id,
                        task.subject,
                        task.description,
                        task.active_form,
                        task.owner,
                        task.status.value,
                        json.dumps(task.blocks),
                        json.dumps(task.blocked_by),
                        json.dumps(task.metadata) if task.metadata is not None else None,
                        task.created_at,
                        task.updated_at,
                    ),
                )
        return task

    async def get_task(self, task_list_id: str, task_id: str) -> Task | None:
        async with self._pool.acquire() as conn:
            async with conn.cursor(DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM tasks WHERE task_list_id = %s AND id = %s",
                    (task_list_id, task_id),
                )
                row = await cur.fetchone()
        return _row_to_task(row) if row else None

    async def list_tasks(self, task_list_id: str) -> list[Task]:
        async with self._pool.acquire() as conn:
            async with conn.cursor(DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM tasks WHERE task_list_id = %s "
                    "ORDER BY CAST(id AS UNSIGNED)",
                    (task_list_id,),
                )
                rows = await cur.fetchall()
        return [_row_to_task(r) for r in rows]

    async def _write_task(self, task: Task) -> None:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """UPDATE tasks SET
                       subject = %s, description = %s, active_form = %s,
                       owner = %s, status = %s, blocks = %s, blocked_by = %s,
                       metadata = %s, updated_at = %s
                       WHERE task_list_id = %s AND id = %s""",
                    (
                        task.subject,
                        task.description,
                        task.active_form,
                        task.owner,
                        task.status.value,
                        json.dumps(task.blocks),
                        json.dumps(task.blocked_by),
                        json.dumps(task.metadata) if task.metadata is not None else None,
                        task.updated_at,
                        task.task_list_id,
                        task.id,
                    ),
                )

    async def update_task(
        self,
        task_list_id: str,
        task_id: str,
        *,
        subject: str | None = None,
        description: str | None = None,
        active_form: str | None = None,
        status: TaskStatus | None = None,
        owner: str | None = _UNSET,
        metadata: dict | None = None,
        add_blocks: list[str] | None = None,
        add_blocked_by: list[str] | None = None,
    ) -> Task | None:
        task = await self.get_task(task_list_id, task_id)
        if task is None:
            return None

        if subject is not None:
            task.subject = subject
        if description is not None:
            task.description = description
        if active_form is not None:
            task.active_form = active_form
        if status is not None:
            task.status = status
        if owner is not _UNSET:
            task.owner = owner
        if metadata is not None:
            merged = dict(task.metadata or {})
            for k, v in metadata.items():
                if v is None:
                    merged.pop(k, None)
                else:
                    merged[k] = v
            task.metadata = merged or None

        # Reciprocal dependency wiring: A blocks B  <=>  B blockedBy A. The other
        # side of each edge is read-modify-written separately (autocommit, no txn).
        for other_id in add_blocks or []:
            other = await self.get_task(task_list_id, other_id)
            if other is None:
                continue
            if other_id not in task.blocks:
                task.blocks.append(other_id)
            if task_id not in other.blocked_by:
                other.blocked_by.append(task_id)
                other.updated_at = datetime.now(timezone.utc)
                await self._write_task(other)
        for other_id in add_blocked_by or []:
            other = await self.get_task(task_list_id, other_id)
            if other is None:
                continue
            if other_id not in task.blocked_by:
                task.blocked_by.append(other_id)
            if task_id not in other.blocks:
                other.blocks.append(task_id)
                other.updated_at = datetime.now(timezone.utc)
                await self._write_task(other)

        task.updated_at = datetime.now(timezone.utc)
        await self._write_task(task)
        return task

    async def delete_task(self, task_list_id: str, task_id: str) -> bool:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                result = await cur.execute(
                    "DELETE FROM tasks WHERE task_list_id = %s AND id = %s",
                    (task_list_id, task_id),
                )
        if result == 0:
            return False
        # Cascade: strip dangling references from every other task in the list.
        for other in await self.list_tasks(task_list_id):
            changed = False
            if task_id in other.blocks:
                other.blocks.remove(task_id)
                changed = True
            if task_id in other.blocked_by:
                other.blocked_by.remove(task_id)
                changed = True
            if changed:
                other.updated_at = datetime.now(timezone.utc)
                await self._write_task(other)
        return True
