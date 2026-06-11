"""Ad-hoc verification of the task system against the mock DB.

Run from backend/:  python scripts/test_tasks.py
Exercises create -> chain (blocked_by) -> list -> complete -> auto-unblock,
metadata merge/delete, delete cascade, and monotonic (no-reuse) ids.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.mock import MockMemoryDatabase  # noqa: E402
from app.models.domain import TaskStatus  # noqa: E402


async def main() -> None:
    db = MockMemoryDatabase()
    lst = "session-abc"

    t1 = await db.create_task(lst, "Build feature", "Implement the thing")
    t2 = await db.create_task(lst, "Write tests", "Cover the thing", active_form="Writing tests")
    assert (t1.id, t2.id) == ("1", "2"), (t1.id, t2.id)

    # t2 is blocked by t1
    await db.update_task(lst, t2.id, add_blocked_by=[t1.id])
    t1r = await db.get_task(lst, t1.id)
    t2r = await db.get_task(lst, t2.id)
    assert t2r.blocked_by == [t1.id], t2r.blocked_by
    assert t1r.blocks == [t2.id], t1r.blocks  # reciprocal wiring
    print("OK: dependency wired reciprocally")

    # complete t1 -> t2 should become unblocked in the open-blocker view
    await db.update_task(lst, t1.id, status=TaskStatus.COMPLETED)
    by_id = {t.id: t for t in await db.list_tasks(lst)}
    open_blockers = [
        b for b in by_id[t2.id].blocked_by
        if by_id[b].status != TaskStatus.COMPLETED
    ]
    assert open_blockers == [], "t2 should auto-unblock"
    print("OK: completed blocker drops off")

    # metadata merge + null-delete
    await db.update_task(lst, t2.id, metadata={"priority": "high", "tmp": 1})
    await db.update_task(lst, t2.id, metadata={"tmp": None, "owner_note": "x"})
    t2r = await db.get_task(lst, t2.id)
    assert t2r.metadata == {"priority": "high", "owner_note": "x"}, t2r.metadata
    print("OK: metadata merge + null-delete")

    # delete cascade: removing t1 strips refs from t2
    assert await db.delete_task(lst, t1.id) is True
    t2r = await db.get_task(lst, t2.id)
    assert t2r.blocked_by == [], t2r.blocked_by
    print("OK: delete cascade removed dangling ref")

    # monotonic ids: next create is higher than any used, even after delete
    t3 = await db.create_task(lst, "Third", "next id")
    assert t3.id == "3", t3.id
    print("OK: ids monotonic, not reused")

    # scoping: a different session has its own list + counter
    other = await db.create_task("session-xyz", "Other", "isolated")
    assert other.id == "1", other.id
    assert len(await db.list_tasks(lst)) == 2
    assert len(await db.list_tasks("session-xyz")) == 1
    print("OK: per-session isolation")

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
