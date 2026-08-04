import os
from functools import lru_cache


class Settings:
    def __init__(self) -> None:
        self.db_type: str = os.getenv("DB_TYPE", "mysql")
        self.mysql_host: str = os.getenv("MYSQL_HOST", "127.0.0.1")
        self.mysql_port: int = int(os.getenv("MYSQL_PORT", "3306"))
        self.mysql_user: str = os.getenv("MYSQL_USER", "root")
        self.mysql_password: str = os.getenv("MYSQL_PASSWORD", "")
        self.mysql_database: str = os.getenv("MYSQL_DATABASE", "augentia")
        self.sqlite_path: str = os.getenv("SQLITE_PATH", ".local/augentia.db")
        self.augentia_home: str = os.getenv(
            "AUGENTIA_HOME",
            os.path.join(os.path.expanduser("~"), ".augentia"),
        )
        self.worktree_root: str = os.getenv(
            "AUGENTIA_WORKTREE_ROOT",
            os.path.join(os.path.expanduser("~"), ".augentia", "worktrees"),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
