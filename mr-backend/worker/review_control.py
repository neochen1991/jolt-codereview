from __future__ import annotations

from typing import Any


INTERRUPTED_JOB_STATUSES = {"cancelled", "paused"}


class ReviewJobInterrupted(RuntimeError):
    def __init__(self, status: str):
        self.status = status
        super().__init__(f"review_job_{status}")


def ensure_review_job_active(conn: Any, job_id: str) -> None:
    row = conn.execute("SELECT status FROM review_jobs WHERE id = %s", (job_id,)).fetchone()
    if not row:
        raise ReviewJobInterrupted("missing")
    status = str(row["status"] or "")
    if status in INTERRUPTED_JOB_STATUSES:
        raise ReviewJobInterrupted(status)
