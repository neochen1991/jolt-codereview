from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from config import db_path


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
    driver = str((config.get("server") or {}).get("database_driver") or "sqlite").strip().lower()
    if driver == "postgres":
        return PostgresCompatConnection(config)
    if driver not in {"", "sqlite"}:
        raise RuntimeError(f"Unsupported database driver: {driver}")
    path = db_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


class PostgresCompatConnection:
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
        special = self._special_cursor(sql, params_list)
        if special is not None:
            return special
        translated = translate_sqlite_to_postgres(sql)
        cursor = self._conn.execute(translated, params_list)
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

    def _special_cursor(self, sql: str, params: list[Any]) -> CompatCursor | None:
        if re.match(r"^PRAGMA\s+foreign_key_list", sql, re.I):
            return CompatCursor([])
        table_info = re.match(r"^PRAGMA\s+table_info\((.+)\)$", sql, re.I)
        if table_info:
            table_name = table_info.group(1).strip().strip("\"'`")
            cursor = self._conn.execute(
                """
                SELECT column_name AS name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
                """,
                [table_name],
            )
            return CompatCursor(_wrap_rows(cursor.fetchall()), cursor.rowcount)
        if re.search(r"\bFROM\s+sqlite_master\b", sql, re.I):
            if re.search(r"\bsql\s+LIKE\s+'%REFERENCES%'", sql, re.I):
                return CompatCursor([])
            literal = re.search(r"\bname\s*=\s*'([^']+)'", sql, re.I)
            table_name = literal.group(1) if literal else (str(params[0]) if params else "")
            if not table_name:
                return CompatCursor([])
            cursor = self._conn.execute(
                """
                SELECT table_name AS name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = %s
                """,
                [table_name],
            )
            return CompatCursor(_wrap_rows(cursor.fetchall()), cursor.rowcount)
        if re.match(r"^PRAGMA\b", sql, re.I):
            return CompatCursor([])
        return None


def _wrap_rows(rows: list[dict[str, Any]]) -> list[CompatRow]:
    return [CompatRow(dict(row), list(row.keys())) for row in rows]


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


def translate_sqlite_to_postgres(sql: str) -> str:
    translated = sql.strip().rstrip(";")
    translated = re.sub(r"BEGIN\s+IMMEDIATE", "BEGIN", translated, flags=re.I)
    translated = re.sub(r"datetime\(\s*'now'\s*,\s*\?\s*\)", "(CURRENT_TIMESTAMP + %s::interval)", translated, flags=re.I)
    translated = re.sub(
        r"datetime\(\s*'now'\s*,\s*'([^']+)'\s*\)",
        lambda match: f"(CURRENT_TIMESTAMP + INTERVAL '{match.group(1)}')",
        translated,
        flags=re.I,
    )
    translated = re.sub(r"datetime\(\s*'now'\s*\)", "CURRENT_TIMESTAMP", translated, flags=re.I)
    translated = re.sub(r"^INSERT\s+OR\s+IGNORE\s+INTO\s+", "INSERT INTO ", translated, flags=re.I)
    if re.match(r"^INSERT\s+INTO\s+", translated, re.I) and not re.search(r"\bON\s+CONFLICT\b", translated, re.I):
        translated = f"{translated} ON CONFLICT DO NOTHING"
    translated = replace_qmark_placeholders(translated)
    return translated


def replace_qmark_placeholders(sql: str) -> str:
    output: list[str] = []
    in_single = False
    in_double = False
    index = 0
    while index < len(sql):
        char = sql[index]
        next_char = sql[index + 1] if index + 1 < len(sql) else ""
        if char == "'" and not in_double:
            output.append(char)
            if in_single and next_char == "'":
                output.append(next_char)
                index += 2
                continue
            in_single = not in_single
            index += 1
            continue
        if char == '"' and not in_single:
            output.append(char)
            in_double = not in_double
            index += 1
            continue
        if char == "?" and not in_single and not in_double:
            output.append("%s")
            index += 1
            continue
        output.append(char)
        index += 1
    return "".join(output)
