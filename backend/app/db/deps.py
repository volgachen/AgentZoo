import os

from app.config import get_settings
from app.db.interface import IAgentDatabase
from app.db.mock import MockMemoryDatabase
from app.db.mysql import MySqlDatabase
from app.db.sqlite import SqliteDatabase

_db: IAgentDatabase | None = None
_mock_db: MockMemoryDatabase | None = None
_sqlite_db: SqliteDatabase | None = None


def _get_mock_db() -> MockMemoryDatabase:
    global _mock_db
    if _mock_db is None:
        _mock_db = MockMemoryDatabase()
    return _mock_db


def _get_sqlite_db(path: str) -> SqliteDatabase:
    global _sqlite_db
    if _sqlite_db is None:
        _sqlite_db = SqliteDatabase(path)
    return _sqlite_db


async def init_db() -> None:
    global _db

    db_type = os.getenv("DB_TYPE", "mock").lower()
    settings = get_settings()
    if db_type == "mock":
        _db = _get_mock_db()
        return
    if db_type == "sqlite":
        _db = _get_sqlite_db(settings.sqlite_path)
        return
    if db_type != "mysql":
        raise ValueError(f"Unsupported DB_TYPE: {db_type}")

    mysql = MySqlDatabase(settings)
    await mysql.connect()
    _db = mysql


async def close_db() -> None:
    global _db, _mock_db, _sqlite_db
    if isinstance(_db, MySqlDatabase):
        await _db.close()
    if isinstance(_db, SqliteDatabase):
        await _db.close()
    _db = None
    _mock_db = None
    _sqlite_db = None


def get_db() -> IAgentDatabase:
    if _db is not None:
        return _db
    return _get_mock_db()
