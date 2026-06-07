"""Test the write and edit tools' branches without running the backend.

Calls WriteTool.execute() and EditTool.execute() directly to verify:
  write:
    - create a new file (parent dirs auto-created)
    - overwrite an existing file ("Updated")
  edit:
    - unique replacement
    - replace_all over multiple occurrences
    - non-unique match without replace_all is rejected
    - old_string not found is rejected
    - identical old/new is rejected
    - missing file is rejected

No uvicorn, no model, no network needed.
"""
import asyncio
import os
import sys

import _common  # noqa: F401 — sets sys.path so `app.*` imports resolve

import app.adapters.tools  # noqa: F401 — triggers @register_tool side effects
from app.adapters.tools.registry import load_tools
from _common import ok, fail, info, section

_DIR = os.path.join(os.path.dirname(__file__), "..", "tmp", "edit_test")
_FILE = os.path.join(_DIR, "sample.txt")
_NESTED = os.path.join(_DIR, "deep", "nested", "new.txt")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


async def main() -> int:
    section("write + edit tool branches")
    write, edit = load_tools(["write", "edit"])
    failures = 0

    # --- write: create with auto-made parent dirs ---
    info("--- write: create (nested dirs) ---")
    result = await write.execute(file_path=_NESTED, content="x\n")
    if result.startswith("[Created]") and _read(_NESTED) == "x\n":
        ok("write: created file and parent directories")
    else:
        fail(f"write create: {result!r}")
        failures += 1

    # --- write: overwrite existing ---
    info("--- write: overwrite ---")
    await write.execute(file_path=_FILE, content="old content\n")
    result = await write.execute(file_path=_FILE, content="alpha beta alpha\n")
    if result.startswith("[Updated]") and _read(_FILE) == "alpha beta alpha\n":
        ok("write: overwrote existing file")
    else:
        fail(f"write overwrite: {result!r}")
        failures += 1

    # --- edit: non-unique without replace_all is rejected ---
    info("--- edit: non-unique rejected ---")
    result = await edit.execute(file_path=_FILE, old_string="alpha", new_string="A")
    if result.startswith("[Error]") and "not unique" in result:
        ok("edit: rejected ambiguous match")
    else:
        fail(f"edit non-unique: {result!r}")
        failures += 1

    # --- edit: replace_all ---
    info("--- edit: replace_all ---")
    result = await edit.execute(
        file_path=_FILE, old_string="alpha", new_string="A", replace_all=True
    )
    if "2 replacement" in result and _read(_FILE) == "A beta A\n":
        ok("edit: replaced all occurrences")
    else:
        fail(f"edit replace_all: {result!r} / file={_read(_FILE)!r}")
        failures += 1

    # --- edit: unique replacement ---
    info("--- edit: unique ---")
    result = await edit.execute(file_path=_FILE, old_string="beta", new_string="B")
    if result.startswith("[Edited]") and _read(_FILE) == "A B A\n":
        ok("edit: unique replacement applied")
    else:
        fail(f"edit unique: {result!r} / file={_read(_FILE)!r}")
        failures += 1

    # --- edit: not found ---
    info("--- edit: not found ---")
    result = await edit.execute(file_path=_FILE, old_string="zzz", new_string="q")
    if result.startswith("[Error]") and "not found" in result:
        ok("edit: rejected missing old_string")
    else:
        fail(f"edit not-found: {result!r}")
        failures += 1

    # --- edit: identical old/new ---
    info("--- edit: identical ---")
    result = await edit.execute(file_path=_FILE, old_string="A", new_string="A")
    if result.startswith("[Error]") and "identical" in result:
        ok("edit: rejected no-op replacement")
    else:
        fail(f"edit identical: {result!r}")
        failures += 1

    # --- edit: missing file ---
    info("--- edit: missing file ---")
    result = await edit.execute(
        file_path="does/not/exist.txt", old_string="a", new_string="b"
    )
    if result.startswith("[Error]") and "not found" in result:
        ok("edit: rejected missing file")
    else:
        fail(f"edit missing-file: {result!r}")
        failures += 1

    # cleanup
    for p in (_NESTED, _FILE):
        if os.path.isfile(p):
            os.remove(p)

    if failures:
        print(f"\n{failures} write/edit branch(es) failed.")
        return 1
    print("\nAll write/edit branches behaved as expected.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
