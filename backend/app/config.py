import os
from functools import lru_cache


class Settings:
    def __init__(self) -> None:
        self.db_type: str = os.getenv("DB_TYPE", "mysql")
        self.mysql_host: str = os.getenv("MYSQL_HOST", "127.0.0.1")
        self.mysql_port: int = int(os.getenv("MYSQL_PORT", "3306"))
        self.mysql_user: str = os.getenv("MYSQL_USER", "root")
        self.mysql_password: str = os.getenv("MYSQL_PASSWORD", "")
        self.mysql_database: str = os.getenv("MYSQL_DATABASE", "agentzoo")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
