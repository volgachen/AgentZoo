"""Shared helpers for standalone test scripts."""
import os
import sys
from pathlib import Path

# Make `app.*` importable when running `python scripts/foo.py` from backend/.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

BASE_URL = os.getenv("AGENTZOO_BASE_URL", "http://localhost:12598")
WS_BASE_URL = BASE_URL.replace("http://", "ws://").replace("https://", "wss://")


class Colors:
    OK = "\033[92m"
    WARN = "\033[93m"
    FAIL = "\033[91m"
    DIM = "\033[2m"
    END = "\033[0m"


def ok(msg: str) -> None:
    print(f"{Colors.OK}[PASS]{Colors.END} {msg}")


def fail(msg: str) -> None:
    print(f"{Colors.FAIL}[FAIL]{Colors.END} {msg}")


def info(msg: str) -> None:
    print(f"{Colors.DIM}  {msg}{Colors.END}")


def section(msg: str) -> None:
    print(f"\n=== {msg} ===")
