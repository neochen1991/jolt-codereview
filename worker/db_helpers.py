from __future__ import annotations

from typing import Any


def table_exists(conn: Any, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT table_name AS name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = ?
        """,
        (table_name,),
    ).fetchone()
    return bool(row)
