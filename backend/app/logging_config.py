import logging
import os
import sys

_configured = False


def setup_logging() -> None:
    """Configure root logger from env. Idempotent — safe to call from
    multiple entry points (app.main, scripts/_common) without duplicating
    handlers or log lines."""
    global _configured
    if _configured:
        return
    _configured = True
    debug = os.getenv("AGENTZOO_DEBUG", "").lower() in ("1", "true", "yes")
    level_name = os.getenv("AGENTZOO_LOG_LEVEL", "DEBUG" if debug else "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    fmt = (
        "%(asctime)s [%(levelname)s] %(name)s:%(funcName)s:%(lineno)d: %(message)s"
        if level <= logging.DEBUG
        else "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Tame noisy third-party libs unless explicitly in DEBUG.
    if level > logging.DEBUG:
        for name in ("httpx", "httpcore", "openai", "websockets", "asyncio"):
            logging.getLogger(name).setLevel(logging.WARNING)

    logging.getLogger("agentzoo").info(
        "Logging configured: level=%s debug=%s", level_name, debug
    )
