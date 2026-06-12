from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from db_compat import _wrap_rows, translate_sqlite_schema_to_postgres, translate_sqlite_to_postgres  # noqa: E402


def assert_contains(actual: str, expected: str) -> None:
    if expected not in actual:
        raise AssertionError(f"Expected SQL to contain:\n{expected}\n\nActual SQL:\n{actual}")


ddl = translate_sqlite_to_postgres(
    """
    CREATE TABLE IF NOT EXISTS auth_sessions (
      id TEXT PRIMARY KEY,
      expires_at TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """
)
assert_contains(ddl, "created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)")

schema_only = translate_sqlite_schema_to_postgres(
    """
    CREATE TABLE IF NOT EXISTS legacy_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      occurred_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      active BOOLEAN NOT NULL DEFAULT 1
    );
    """
)
assert_contains(schema_only, "id SERIAL PRIMARY KEY")
assert_contains(schema_only, "occurred_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)")
assert_contains(schema_only, "active INTEGER NOT NULL DEFAULT 1")

session_lookup = translate_sqlite_to_postgres(
    """
    SELECT user_id
    FROM auth_sessions
    WHERE token_hash = ?
      AND status = 'active'
      AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
    """
)
assert_contains(session_lookup, "token_hash = %s")
assert_contains(session_lookup, "NULLIF(expires_at, '')::timestamptz > CURRENT_TIMESTAMP")

reclaim_queue = translate_sqlite_to_postgres(
    """
    UPDATE review_jobs
    SET status = 'queued'
    WHERE status = 'reviewing'
      AND (heartbeat_at IS NULL OR heartbeat_at < datetime('now', ?))
    """
)
assert_contains(reclaim_queue, "NULLIF(heartbeat_at, '')::timestamptz < (CURRENT_TIMESTAMP + %s::interval)")

health_query = translate_sqlite_to_postgres(
    """
    SELECT COUNT(*) AS active
    FROM review_jobs rj
    WHERE COALESCE(rj.heartbeat_at, rj.locked_at, rj.updated_at) >= datetime('now', '-60 seconds')
    """
)
assert_contains(
    health_query,
    "NULLIF(COALESCE(rj.heartbeat_at, rj.locked_at, rj.updated_at), '')::timestamptz >= (CURRENT_TIMESTAMP + INTERVAL '-60 seconds')",
)

feedback_query = translate_sqlite_to_postgres(
    """
    SELECT uf.dedupe_hash
    FROM user_feedback uf
    WHERE uf.created_at >= datetime('now', '-90 days')
    """
)
assert_contains(feedback_query, "NULLIF(uf.created_at, '')::timestamptz >= (CURRENT_TIMESTAMP + INTERVAL '-90 days')")

empty_timestamp_guard = translate_sqlite_to_postgres(
    """
    SELECT *
    FROM review_baseline_suppressions
    WHERE expires_at = '' OR expires_at > CURRENT_TIMESTAMP
    """
)
assert_contains(empty_timestamp_guard, "NULLIF(expires_at, '')::timestamptz > CURRENT_TIMESTAMP")

scalar_min_max = translate_sqlite_to_postgres(
    """
    UPDATE expert_profiles
    SET max_findings = MAX(expert_profiles.max_findings, excluded.max_findings),
        max_tool_calls = MIN(expert_profiles.max_tool_calls, excluded.max_tool_calls)
    """
)
assert_contains(scalar_min_max, "max_findings = GREATEST(expert_profiles.max_findings, excluded.max_findings)")
assert_contains(scalar_min_max, "max_tool_calls = LEAST(expert_profiles.max_tool_calls, excluded.max_tool_calls)")

epoch_diff = translate_sqlite_to_postgres(
    """
    SELECT strftime('%s', rr.completed_at) - strftime('%s', rr.started_at) AS run_seconds
    FROM review_runs rr
    """
)
assert_contains(epoch_diff, "EXTRACT(EPOCH FROM NULLIF(rr.completed_at, '')::timestamptz)")
assert_contains(epoch_diff, "EXTRACT(EPOCH FROM NULLIF(rr.started_at, '')::timestamptz)")

julian_diff = translate_sqlite_to_postgres(
    """
    SELECT (julianday(rr.completed_at) - julianday(rr.started_at)) * 86400 AS duration_seconds
    FROM review_runs rr
    """
)
assert_contains(julian_diff, "EXTRACT(EPOCH FROM NULLIF(rr.completed_at, '')::timestamptz) / 86400.0")
assert_contains(julian_diff, "EXTRACT(EPOCH FROM NULLIF(rr.started_at, '')::timestamptz) / 86400.0")

rows = _wrap_rows([{"created_at": datetime(2026, 6, 12, 10, 30, 45)}])
if rows[0]["created_at"] != "2026-06-12 10:30:45":
    raise AssertionError(f"datetime normalization failed: {rows[0]['created_at']!r}")

print("Python PG SQL compatibility translation checks passed.")
