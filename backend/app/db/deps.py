import os

from app.config import get_settings
from app.db.interface import IAgentDatabase
from app.db.mock import MockMemoryDatabase
from app.db.mysql import MySqlDatabase

_db: IAgentDatabase | None = None
_mock_db: MockMemoryDatabase | None = None


def _get_mock_db() -> MockMemoryDatabase:
    global _mock_db
    if _mock_db is None:
        _mock_db = MockMemoryDatabase()
    return _mock_db


async def init_db() -> None:
    global _db

    db_type = os.getenv("DB_TYPE", "mock")
    if db_type == "mock":
        _db = _get_mock_db()
        return

    settings = get_settings()
    mysql = MySqlDatabase(settings)
    await mysql.connect()
    _db = mysql


async def close_db() -> None:
    global _db, _mock_db
    if isinstance(_db, MySqlDatabase):
        await _db.close()
    _db = None
    _mock_db = None


def get_db() -> IAgentDatabase:
    if _db is not None:
        return _db
    return _get_mock_db()
