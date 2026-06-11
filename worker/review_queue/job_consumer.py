from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from db_compat import open_app_database

HEARTBEAT_SECONDS = 10
RECLAIM_AFTER_SECONDS = 60
MAX_ATTEMPTS = 3
MAX_BACKOFF_SECONDS = 300
ACTIVE_STATUSES = ("fetching", "pre_scanning", "reviewing", "judging")


def backoff_seconds(attempt: int) -> int:
    normalized_attempt = max(1, int(attempt))
    return min(MAX_BACKOFF_SECONDS, 5 * (2 ** (normalized_attempt - 1)))


def start_heartbeat(db_file: Path, job_id: str, interval_seconds: int = HEARTBEAT_SECONDS, config: dict[str, Any] | None = None) -> threading.Thread:
    def run() -> None:
        conn = open_app_database(config) if config else sqlite3.connect(db_file, timeout=15)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 5000")
            while True:
                time.sleep(interval_seconds)
                placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
                try:
                    result = conn.execute(
                        f"""
                        UPDATE review_jobs
                        SET heartbeat_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ? AND status IN ({placeholders})
                        """,
                        (job_id, *ACTIVE_STATUSES),
                    )
                    conn.commit()
                except Exception as exc:
                    if "locked" not in str(exc).lower():
                        raise
                    conn.rollback()
                    continue
                if result.rowcount == 0:
                    break
        finally:
            conn.close()

    thread = threading.Thread(target=run, name=f"review-job-heartbeat-{job_id}", daemon=True)
    thread.start()
    return thread
