from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.db.mock import MockMemoryDatabase
from app.models.domain import (
    AgentTemplate,
    Message,
    PluginInstance,
    PluginLog,
    PluginRun,
    Session,
    Task,
)


class SqliteDatabase(MockMemoryDatabase):
    """Python-only local persistence backend.

    This backend keeps the same in-memory behavior as MockMemoryDatabase, but
    snapshots all runtime state into a SQLite file after each write. It is meant
    for local development and single-user desktop usage where installing and
    running MySQL would be unnecessary friction.
    """

    def __init__(self, db_path: str | Path) -> None:
        super().__init__()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS local_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self._conn.commit()
        self._load_snapshot()

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        self._save_snapshot()
        self._conn.close()

    def _load_snapshot(self) -> None:
        row = self._conn.execute(
            "SELECT value FROM local_state WHERE key = ?",
            ("snapshot",),
        ).fetchone()
        if row is None:
            self._save_snapshot()
            return

        data = json.loads(row[0])
        agents = data.get("agents", {})
        self._agents.update({k: AgentTemplate(**v) for k, v in agents.items()})
        self._sessions = {
            k: Session(**v) for k, v in data.get("sessions", {}).items()
        }
        self._messages = {
            k: [Message(**m) for m in v]
            for k, v in data.get("messages", {}).items()
        }
        self._plugin_instances = {
            k: PluginInstance(**v)
            for k, v in data.get("plugin_instances", {}).items()
        }
        self._plugin_runs = {
            k: PluginRun(**v) for k, v in data.get("plugin_runs", {}).items()
        }
        self._plugin_logs = {
            int(k): PluginLog(**v) for k, v in data.get("plugin_logs", {}).items()
        }
        self._plugin_log_counter = int(data.get("plugin_log_counter", 0))
        self._tasks = {
            list_id: {task_id: Task(**task) for task_id, task in tasks.items()}
            for list_id, tasks in data.get("tasks", {}).items()
        }
        self._task_counters = {
            k: int(v) for k, v in data.get("task_counters", {}).items()
        }

    def _save_snapshot(self) -> None:
        data = {
            "agents": {
                k: v.model_dump(mode="json") for k, v in self._agents.items()
            },
            "sessions": {
                k: v.model_dump(mode="json") for k, v in self._sessions.items()
            },
            "messages": {
                k: [m.model_dump(mode="json") for m in v]
                for k, v in self._messages.items()
            },
            "plugin_instances": {
                k: v.model_dump(mode="json")
                for k, v in self._plugin_instances.items()
            },
            "plugin_runs": {
                k: v.model_dump(mode="json")
                for k, v in self._plugin_runs.items()
            },
            "plugin_logs": {
                str(k): v.model_dump(mode="json")
                for k, v in self._plugin_logs.items()
            },
            "plugin_log_counter": self._plugin_log_counter,
            "tasks": {
                list_id: {
                    task_id: task.model_dump(mode="json")
                    for task_id, task in tasks.items()
                }
                for list_id, tasks in self._tasks.items()
            },
            "task_counters": self._task_counters,
        }
        self._conn.execute(
            """
            INSERT INTO local_state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            ("snapshot", json.dumps(data, ensure_ascii=False)),
        )
        self._conn.commit()

    async def create_agent(self, template: AgentTemplate) -> AgentTemplate:
        result = await super().create_agent(template)
        self._save_snapshot()
        return result

    async def update_agent(self, agent_id: str, **kwargs: Any) -> AgentTemplate:
        result = await super().update_agent(agent_id, **kwargs)
        self._save_snapshot()
        return result

    async def delete_agent(self, agent_id: str) -> None:
        await super().delete_agent(agent_id)
        self._save_snapshot()

    async def create_session(self, agent_id: str, working_dir: str | None = None, **kwargs: Any) -> Session:
        result = await super().create_session(agent_id, working_dir, **kwargs)
        self._save_snapshot()
        return result

    async def update_session_title(self, session_id: str, title: str) -> Session:
        result = await super().update_session_title(session_id, title)
        self._save_snapshot()
        return result

    async def update_session_status(self, session_id: str, status: Any) -> Session:
        result = await super().update_session_status(session_id, status)
        self._save_snapshot()
        return result

    async def add_message(self, session_id: str, role: Any, content: str, **kwargs: Any) -> Message:
        result = await super().add_message(session_id, role, content, **kwargs)
        self._save_snapshot()
        return result

    async def create_plugin_instance(self, plugin_id: str, display_name: str, **kwargs: Any) -> PluginInstance:
        result = await super().create_plugin_instance(plugin_id, display_name, **kwargs)
        self._save_snapshot()
        return result

    async def update_plugin_instance(self, instance_id: str, **kwargs: Any) -> PluginInstance:
        result = await super().update_plugin_instance(instance_id, **kwargs)
        self._save_snapshot()
        return result

    async def delete_plugin_instance(self, instance_id: str) -> None:
        await super().delete_plugin_instance(instance_id)
        self._save_snapshot()

    async def create_plugin_run(self, plugin_instance_id: str, plugin_id: str, **kwargs: Any) -> PluginRun:
        result = await super().create_plugin_run(plugin_instance_id, plugin_id, **kwargs)
        self._save_snapshot()
        return result

    async def update_plugin_run(self, run_id: str, **kwargs: Any) -> PluginRun:
        result = await super().update_plugin_run(run_id, **kwargs)
        self._save_snapshot()
        return result

    async def add_plugin_log(self, plugin_instance_id: str, plugin_run_id: str, stream: str, line: str, **kwargs: Any) -> PluginLog:
        result = await super().add_plugin_log(plugin_instance_id, plugin_run_id, stream, line, **kwargs)
        self._save_snapshot()
        return result

    async def create_task(self, task_list_id: str, subject: str, description: str, **kwargs: Any) -> Task:
        result = await super().create_task(task_list_id, subject, description, **kwargs)
        self._save_snapshot()
        return result

    async def update_task(self, task_list_id: str, task_id: str, **kwargs: Any) -> Task | None:
        result = await super().update_task(task_list_id, task_id, **kwargs)
        self._save_snapshot()
        return result

    async def delete_task(self, task_list_id: str, task_id: str) -> bool:
        result = await super().delete_task(task_list_id, task_id)
        if result:
            self._save_snapshot()
        return result
