from app.db.interface import IAgentDatabase
from app.db.mock import MockMemoryDatabase

_db_instance: IAgentDatabase = MockMemoryDatabase()


def get_db() -> IAgentDatabase:
    return _db_instance
