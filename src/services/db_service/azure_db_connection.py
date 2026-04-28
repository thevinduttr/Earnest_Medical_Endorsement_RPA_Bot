from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pyodbc


_DB_ENV_PATH = Path("config/env/db.env")
_DB_ENV_LOADED = False


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


def load_db_environment(env_path: Path = _DB_ENV_PATH) -> None:
    global _DB_ENV_LOADED
    if _DB_ENV_LOADED:
        return

    _load_env_file(env_path)
    _DB_ENV_LOADED = True


def get_db_connection_string() -> str:
    load_db_environment()

    connection_string = str(os.getenv("DB_CONNECTION_STRING") or "").strip()
    if connection_string:
        return connection_string

    driver = str(os.getenv("DB_DRIVER") or "{SQL Server}").strip()
    server = str(os.getenv("DB_SERVER") or "").strip()
    database = str(os.getenv("DB_DATABASE") or "").strip()
    username = str(os.getenv("DB_USERNAME") or "").strip()
    password = str(os.getenv("DB_PASSWORD") or "").strip()

    missing = [
        name
        for name, value in (
            ("DB_SERVER", server),
            ("DB_DATABASE", database),
            ("DB_USERNAME", username),
            ("DB_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            "Database configuration is missing. Set DB_CONNECTION_STRING or required fields: "
            + ", ".join(missing)
        )

    return (
        f"DRIVER={driver};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password}"
    )


class AzureSQLConnection:
    def __init__(self, logger=None):
        self.logger = logger
        self.connection: Optional[pyodbc.Connection] = None

    def connect(self) -> pyodbc.Connection:
        if self.connection is None:
            self.connection = pyodbc.connect(get_db_connection_string(), timeout=30)
            if self.logger:
                self.logger.info("[Database] Connected to Azure SQL.")
        return self.connection

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def __enter__(self) -> "AzureSQLConnection":
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        self.close()
