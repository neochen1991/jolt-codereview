from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from db_compat import open_app_database  # noqa: E402


config_path = os.environ.get("PG_RUNTIME_CONFIG_PATH") or os.environ.get("CONFIG_PATH")
if not config_path:
    raise RuntimeError("Set CONFIG_PATH or PG_RUNTIME_CONFIG_PATH to a PostgreSQL config before running verify_pg_worker_runtime.py")

config = json.loads(Path(config_path).read_text(encoding="utf-8"))
driver = str((config.get("server") or {}).get("database_driver") or "")
if driver != "postgres":
    raise RuntimeError("verify_pg_worker_runtime.py requires server.database_driver=postgres")

conn = open_app_database(config)
try:
    table_info = conn.execute("PRAGMA table_info(review_jobs)").fetchall()
    if not table_info:
        raise AssertionError("PRAGMA table_info compatibility returned no columns")

    table_exists = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", ("review_jobs",)).fetchone()
    if not table_exists:
        raise AssertionError("sqlite_master compatibility did not find review_jobs")

    conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM auth_sessions
        WHERE expires_at IS NULL OR expires_at = '' OR expires_at > CURRENT_TIMESTAMP
        """
    ).fetchone()
    conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM review_jobs
        WHERE heartbeat_at IS NULL OR heartbeat_at < datetime('now', ?)
        """,
        ("-60 seconds",),
    ).fetchone()
    conn.execute(
        """
        SELECT
          strftime('%s', completed_at) - strftime('%s', started_at) AS run_seconds
        FROM review_runs
        WHERE completed_at IS NOT NULL
        LIMIT 5
        """
    ).fetchall()
    conn.execute(
        """
        SELECT AVG((julianday(completed_at) - julianday(started_at)) * 86400) AS avg_seconds
        FROM review_runs
        WHERE completed_at IS NOT NULL
        """
    ).fetchone()
    conn.execute(
        """
        SELECT MAX(max_findings, 1) AS max_findings, MIN(max_tool_calls, 99) AS max_tool_calls
        FROM expert_profiles
        LIMIT 5
        """
    ).fetchall()
    conn.commit()
    print("Python worker PostgreSQL runtime checks passed.")
finally:
    conn.close()
