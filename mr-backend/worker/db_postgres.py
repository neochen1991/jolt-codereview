from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def open_app_database(config: dict[str, Any]):
    driver = str((config.get("server") or {}).get("database_driver") or "postgres").strip().lower()
    if driver and driver != "postgres":
        raise RuntimeError(f"Unsupported database driver: {driver}. Jolt services are PostgreSQL-only.")
    return PostgresConnection(config)


class PostgresConnection:
    dialect = "postgres"

    def __init__(self, config: dict[str, Any]):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL runtime requires psycopg. Run `pip install \"psycopg[binary]>=3.2\"` "
                "or use the provided install script before enabling server.database_driver=postgres."
            ) from exc

        server = config.get("server") or {}
        connection_string = str(server.get("postgres_url") or "").strip()
        if not connection_string:
            raise RuntimeError("PostgreSQL is enabled but server.postgres_url is empty.")
        kwargs: dict[str, Any] = {"row_factory": dict_row}
        if server.get("postgres_user"):
            kwargs["user"] = server.get("postgres_user")
        if server.get("postgres_password"):
            kwargs["password"] = server.get("postgres_password")
        timeout = int(server.get("postgres_query_timeout_seconds") or 120)
        kwargs["connect_timeout"] = max(1, timeout)
        self._psycopg = psycopg
        self._conn = psycopg.connect(connection_string, **kwargs)
        self._conn.autocommit = False

    def execute(self, sql: str, params: Iterable[Any] | None = None):
        sql = sql.strip()
        params_list = list(params or [])
        cursor = self._conn.cursor()
        if sql:
            cursor.execute(prepare_postgres_sql(sql), params_list)
        return cursor

    def executemany(self, sql: str, seq_of_params: Iterable[Iterable[Any]]):
        cursor = self._conn.cursor()
        cursor.executemany(prepare_postgres_sql(sql), list(seq_of_params))
        return cursor

    def executescript(self, sql: str) -> None:
        for statement in split_sql_statements(sql):
            self.execute(statement)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

def split_sql_statements(sql: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    index = 0
    while index < len(sql):
        char = sql[index]
        next_char = sql[index + 1] if index + 1 < len(sql) else ""
        if char == "'" and not in_double:
            current.append(char)
            if in_single and next_char == "'":
                current.append(next_char)
                index += 2
                continue
            in_single = not in_single
            index += 1
            continue
        if char == '"' and not in_single:
            current.append(char)
            in_double = not in_double
            index += 1
            continue
        if char == ";" and not in_single and not in_double:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements


def prepare_postgres_sql(sql: str) -> str:
    return sql.strip().rstrip(";")
