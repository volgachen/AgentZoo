"""Verify SQLite plugin-log session scoping and legacy-schema migration."""

import asyncio
import sqlite3
import tempfile
from pathlib import Path

import _common  # noqa: F401
from _common import ok, section

from app.db.sqlite import SqliteDatabase


async def main() -> int:
    section("SQLite plugin log session scoping")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "legacy.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """CREATE TABLE plugin_logs (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   plugin_instance_id TEXT NOT NULL,
                   plugin_run_id TEXT NOT NULL,
                   ts TEXT NOT NULL,
                   stream TEXT NOT NULL,
                   level TEXT DEFAULT NULL,
                   line TEXT NOT NULL
               )"""
        )
        conn.close()

        db = SqliteDatabase(db_path)
        columns = {
            row["name"] for row in db._conn.execute("PRAGMA table_info(plugin_logs)")
        }
        assert "session_id" in columns
        indexes = {
            row["name"] for row in db._conn.execute("PRAGMA index_list(plugin_logs)")
        }
        assert "idx_plugin_logs_session_ts" in indexes
        ok("legacy plugin_logs schema migrated with session_id and index")

        instance = await db.create_plugin_instance("plugin.test", "Test")
        run = await db.create_plugin_run(instance.id, instance.plugin_id)
        await db.add_plugin_log(
            instance.id, run.id, "plugin", "session-a log", session_id="session-a"
        )
        await db.add_plugin_log(
            instance.id, run.id, "plugin", "session-b log", session_id="session-b"
        )
        await db.add_plugin_log(instance.id, run.id, "system", "global log")

        scoped = await db.list_plugin_logs(
            plugin_instance_id=instance.id, session_id="session-a"
        )
        assert [(log.session_id, log.line) for log in scoped] == [
            ("session-a", "session-a log")
        ]
        all_logs = await db.list_plugin_logs(plugin_run_id=run.id)
        assert len(all_logs) == 3
        ok("session_id is persisted and filters plugin logs without leakage")
        await db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
