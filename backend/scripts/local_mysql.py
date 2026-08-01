#!/usr/bin/env python3
"""Manage a local MySQL/MariaDB server for development.

This script stores database files under a project-local directory and starts a
MySQL-compatible server on localhost, so the backend can run without an
external database server.

It requires MySQL or MariaDB server binaries to be installed locally. The script
looks for mysqld/mariadbd, mysqladmin/mariadb-admin, and mysql/mariadb in PATH,
or you can pass explicit paths with command-line options.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
DEFAULT_BASE_DIR = BACKEND_DIR / ".local" / "mysql"
DEFAULT_DATA_DIR = DEFAULT_BASE_DIR / "data"
DEFAULT_RUN_DIR = DEFAULT_BASE_DIR / "run"
DEFAULT_LOG_DIR = DEFAULT_BASE_DIR / "logs"
DEFAULT_DATABASE = "augentia"
DEFAULT_USER = "root"
DEFAULT_PASSWORD = ""
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3306


class LocalMysqlError(RuntimeError):
    pass


def find_executable(candidates: Iterable[str], explicit: str | None = None) -> str:
    if explicit:
        path = shutil.which(explicit) if os.sep not in explicit else explicit
        if path and Path(path).exists():
            return str(Path(path))
        raise LocalMysqlError(f"Executable not found: {explicit}")

    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return path
    raise LocalMysqlError(
        "Could not find any of these executables in PATH: " + ", ".join(candidates)
    )


def wait_for_port(host: str, port: int, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def run_checked(args: list[str], *, quiet: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode != 0:
        message = [f"Command failed with exit code {result.returncode}:", " ".join(args)]
        if result.stdout.strip():
            message.extend(["stdout:", result.stdout.strip()])
        if result.stderr.strip():
            message.extend(["stderr:", result.stderr.strip()])
        raise LocalMysqlError("\n".join(message))
    if not quiet and result.stdout.strip():
        print(result.stdout.strip())
    return result


def is_initialized(data_dir: Path) -> bool:
    return (data_dir / "mysql").exists() or (data_dir / "performance_schema").exists()


def initialize_data_dir(mysqld: str, data_dir: Path, run_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    if is_initialized(data_dir):
        print(f"Data directory already initialized: {data_dir}")
        return

    print(f"Initializing local MySQL data directory: {data_dir}")
    init_commands = [
        [
            mysqld,
            f"--datadir={data_dir}",
            "--initialize-insecure",
            f"--socket={run_dir / 'mysql.sock'}",
        ],
        [
            mysqld,
            f"--datadir={data_dir}",
            "--initialize-insecure",
        ],
        [
            mysqld,
            f"--datadir={data_dir}",
            "--initialize-insecure",
            f"--basedir={Path(mysqld).resolve().parents[1]}",
        ],
        [
            mysqld,
            f"--datadir={data_dir}",
            "--initialize-insecure",
            "--user=root",
        ],
    ]

    errors: list[str] = []
    for command in init_commands:
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode == 0:
            print("Initialized data directory with an empty root password.")
            return
        errors.append(result.stderr.strip() or result.stdout.strip() or "unknown error")

    mariadb_install_db = shutil.which("mariadb-install-db") or shutil.which("mysql_install_db")
    if mariadb_install_db:
        command = [
            mariadb_install_db,
            f"--datadir={data_dir}",
            "--auth-root-authentication-method=normal",
        ]
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode == 0:
            print("Initialized MariaDB data directory with an empty root password.")
            return
        errors.append(result.stderr.strip() or result.stdout.strip() or "unknown error")

    raise LocalMysqlError(
        "Could not initialize the data directory. Install a local MySQL or MariaDB server "
        "and make sure its server tools are in PATH. Last errors:\n"
        + "\n---\n".join(errors[-3:])
    )


def build_server_args(mysqld: str, data_dir: Path, run_dir: Path, log_dir: Path, host: str, port: int) -> list[str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    return [
        mysqld,
        f"--datadir={data_dir}",
        f"--port={port}",
        f"--bind-address={host}",
        f"--socket={run_dir / 'mysql.sock'}",
        f"--pid-file={run_dir / 'mysqld.pid'}",
        f"--log-error={log_dir / 'mysqld.log'}",
        "--character-set-server=utf8mb4",
        "--collation-server=utf8mb4_unicode_ci",
        "--skip-networking=0",
    ]


def is_server_running(mysqladmin: str, host: str, port: int, user: str, password: str) -> bool:
    args = [mysqladmin, f"--host={host}", f"--port={port}", f"--user={user}"]
    if password:
        args.append(f"--password={password}")
    args.append("ping")
    result = subprocess.run(args, text=True, capture_output=True)
    return result.returncode == 0 and "alive" in (result.stdout + result.stderr).lower()


def start_server(args: argparse.Namespace) -> None:
    mysqld = find_executable(["mysqld", "mariadbd"], args.mysqld)
    mysqladmin = find_executable(["mysqladmin", "mariadb-admin"], args.mysqladmin)
    mysql_client = find_executable(["mysql", "mariadb"], args.mysql)

    base_dir = args.base_dir.resolve()
    data_dir = args.data_dir.resolve() if args.data_dir else base_dir / "data"
    run_dir = base_dir / "run"
    log_dir = base_dir / "logs"
    pid_file = run_dir / "mysqld.pid"

    initialize_data_dir(mysqld, data_dir, run_dir)

    if is_server_running(mysqladmin, args.host, args.port, args.user, args.password):
        print(f"Local MySQL is already running on {args.host}:{args.port}.")
    else:
        command = build_server_args(mysqld, data_dir, run_dir, log_dir, args.host, args.port)
        print(f"Starting local MySQL on {args.host}:{args.port}.")
        log_file = (log_dir / "launcher.log").open("ab")
        process = subprocess.Popen(
            command,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        time.sleep(0.5)
        if process.poll() is not None:
            raise LocalMysqlError(
                f"MySQL exited immediately with code {process.returncode}. "
                f"Check logs in {log_dir}."
            )
        if not wait_for_port(args.host, args.port, args.timeout):
            raise LocalMysqlError(
                f"MySQL did not open {args.host}:{args.port} within {args.timeout} seconds. "
                f"Check logs in {log_dir}."
            )
        print(f"Started local MySQL process with PID {process.pid}.")

    create_database(mysql_client, args.host, args.port, args.user, args.password, args.database)
    print_env(args.host, args.port, args.user, args.password, args.database)
    print(f"Data directory: {data_dir}")
    print(f"Logs directory: {log_dir}")


def create_database(mysql_client: str, host: str, port: int, user: str, password: str, database: str) -> None:
    sql = f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    command = [mysql_client, f"--host={host}", f"--port={port}", f"--user={user}"]
    if password:
        command.append(f"--password={password}")
    command.extend(["--execute", sql])
    run_checked(command, quiet=True)
    print(f"Database is ready: {database}")


def print_env(host: str, port: int, user: str, password: str, database: str) -> None:
    print("\nUse these values in backend/.env:")
    print('DB_TYPE="mysql"')
    print(f'MYSQL_HOST="{host}"')
    print(f'MYSQL_PORT="{port}"')
    print(f'MYSQL_USER="{user}"')
    print(f'MYSQL_PASSWORD="{password}"')
    print(f'MYSQL_DATABASE="{database}"')
    print()


def stop_server(args: argparse.Namespace) -> None:
    mysqladmin = find_executable(["mysqladmin", "mariadb-admin"], args.mysqladmin)
    command = [mysqladmin, f"--host={args.host}", f"--port={args.port}", f"--user={args.user}"]
    if args.password:
        command.append(f"--password={args.password}")
    command.append("shutdown")
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode == 0:
        print(f"Stopped local MySQL on {args.host}:{args.port}.")
        return

    pid_file = (args.base_dir.resolve() / "run" / "mysqld.pid")
    if pid_file.exists():
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to local MySQL process {pid}.")
        return

    raise LocalMysqlError(result.stderr.strip() or result.stdout.strip() or "MySQL is not running.")


def status_server(args: argparse.Namespace) -> None:
    mysqladmin = find_executable(["mysqladmin", "mariadb-admin"], args.mysqladmin)
    if is_server_running(mysqladmin, args.host, args.port, args.user, args.password):
        print(f"Local MySQL is running on {args.host}:{args.port}.")
    else:
        print(f"Local MySQL is not reachable on {args.host}:{args.port}.")
        sys.exit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start a project-local MySQL/MariaDB server.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common_options(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--host", default=DEFAULT_HOST)
        command_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
        command_parser.add_argument("--user", default=DEFAULT_USER)
        command_parser.add_argument("--password", default=DEFAULT_PASSWORD)
        command_parser.add_argument("--database", default=DEFAULT_DATABASE)
        command_parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
        command_parser.add_argument("--mysqladmin", help="Path to mysqladmin or mariadb-admin")

    start = subparsers.add_parser("start", help="Initialize if needed, start MySQL, and create the database")
    add_common_options(start)
    start.add_argument("--data-dir", type=Path, default=None)
    start.add_argument("--mysqld", help="Path to mysqld or mariadbd")
    start.add_argument("--mysql", help="Path to mysql or mariadb client")
    start.add_argument("--timeout", type=float, default=30)

    stop = subparsers.add_parser("stop", help="Stop the local MySQL server")
    add_common_options(stop)

    status = subparsers.add_parser("status", help="Check whether the local MySQL server is reachable")
    add_common_options(status)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "start":
            start_server(args)
        elif args.command == "stop":
            stop_server(args)
        elif args.command == "status":
            status_server(args)
        else:
            raise LocalMysqlError(f"Unknown command: {args.command}")
        return 0
    except LocalMysqlError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
