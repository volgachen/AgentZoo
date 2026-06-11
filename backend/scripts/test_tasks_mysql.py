"""Verify the task system against the live MySQL DB (uses backend/.env).

Run from backend/:  python scripts/test_tasks_mysql.py
Exercises schema auto-create + the full task lifecycle on a throwaway task
list, then cleans up the rows it created.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.config import get_settings  # noqa: E402
from app.db.mysql import MySqlDatabase  # noqa: E402
from app.models.domain import TaskStatus  # noqa: E402

LIST = "verify-tasks-throwaway"


async def main() -> None:
    db = MySqlDatabase(get_settings())
    await db.connect()  # creates tasks + task_counters tables idempotently
    try:
        # clean any leftovers from a prior run
        for t in await db.list_tasks(LIST):
            await db.delete_task(LIST, t.id)

        t1 = await db.create_task(LIST, "Build feature", "Implement the thing")
        t2 = await db.create_task(LIST, "Write tests", "Cover it", active_form="Writing tests")
        print(f"created ids: {t1.id}, {t2.id}")

        await db.update_task(LIST, t2.id, add_blocked_by=[t1.id])
        t1r = await db.get_task(LIST, t1.id)
        t2r = await db.get_task(LIST, t2.id)
        assert t2r.blocked_by == [t1.id], t2r.blocked_by
        assert t1r.blocks == [t2.id], t1r.blocks
        print("OK: dependency wired reciprocally (round-trips through MySQL JSON cols)")

        await db.update_task(LIST, t1.id, status=TaskStatus.COMPLETED)
        by_id = {t.id: t for t in await db.list_tasks(LIST)}
        open_blockers = [
            b for b in by_id[t2.id].blocked_by
            if by_id[b].status != TaskStatus.COMPLETED
        ]
        assert open_blockers == [], open_blockers
        print("OK: completed blocker drops off the open view")

        await db.update_task(LIST, t2.id, metadata={"priority": "high", "tmp": 1})
        await db.update_task(LIST, t2.id, metadata={"tmp": None, "note": "x"})
        t2r = await db.get_task(LIST, t2.id)
        assert t2r.metadata == {"priority": "high", "note": "x"}, t2r.metadata
        print("OK: metadata merge + null-delete persisted")

        assert await db.delete_task(LIST, t1.id) is True
        t2r = await db.get_task(LIST, t2.id)
        assert t2r.blocked_by == [], t2r.blocked_by
        print("OK: delete cascade stripped dangling ref")

        t3 = await db.create_task(LIST, "Third", "next id")
        assert t3.id == "3", t3.id  # monotonic via task_counters, not reused
        print(f"OK: ids monotonic, not reused (next id = {t3.id})")

        # cleanup
        for t in await db.list_tasks(LIST):
            await db.delete_task(LIST, t.id)
        assert await db.list_tasks(LIST) == []
        print("OK: cleaned up")
        print("\nALL MYSQL CHECKS PASSED")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
