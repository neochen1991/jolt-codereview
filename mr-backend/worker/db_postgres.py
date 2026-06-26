from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date, datetime
from typing import Any


class CompatRow(dict[str, Any]):
    def __init__(self, values: dict[str, Any], columns: list[str] | None = None):
        super().__init__(values)
        self._columns = columns or list(values.keys())

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return super().__getitem__(self._columns[key])
        return super().__getitem__(key)

    def keys(self):  # type: ignore[override]
        return super().keys()


class CompatCursor:
    def __init__(self, rows: list[CompatRow] | None = None, rowcount: int = -1):
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchone(self) -> CompatRow | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[CompatRow]:
        return list(self._rows)

    def __iter__(self) -> Iterator[CompatRow]:
        return iter(self._rows)


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

    def execute(self, sql: str, params: Iterable[Any] | None = None) -> CompatCursor:
        sql = sql.strip()
        params_list = list(params or [])
        if not sql:
            return CompatCursor()
        cursor = self._conn.execute(prepare_postgres_sql(sql), params_list)
        rows = _wrap_rows(cursor.fetchall() if cursor.description else [])
        return CompatCursor(rows, cursor.rowcount)

    def executemany(self, sql: str, seq_of_params: Iterable[Iterable[Any]]) -> CompatCursor:
        total = 0
        for params in seq_of_params:
            cursor = self.execute(sql, params)
            total += max(0, int(cursor.rowcount or 0))
        return CompatCursor(rowcount=total)

    def executescript(self, sql: str) -> None:
        for statement in split_sql_statements(sql):
            self.execute(statement)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    @property
    def row_factory(self) -> None:
        return None

    @row_factory.setter
    def row_factory(self, _value: Any) -> None:
        return None

def _wrap_rows(rows: list[dict[str, Any]]) -> list[CompatRow]:
    wrapped: list[CompatRow] = []
    for row in rows:
        values = {key: _normalize_db_value(value) for key, value in dict(row).items()}
        wrapped.append(CompatRow(values, list(row.keys())))
    return wrapped


def _normalize_db_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return value


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
