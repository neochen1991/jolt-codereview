from __future__ import annotations

from typing import Any


INTERRUPTED_JOB_STATUSES = {"cancelled", "paused"}
ACTIVE_MR_REVIEW_STATUSES = ("queued", "fetching", "pre_scanning", "reviewing", "judging")


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


def reclaim_stale_review_jobs(conn: Any, reclaim_after_seconds: int) -> None:
    active_mr_statuses = "'queued', 'fetching', 'pre_scanning', 'reviewing', 'judging'"
    stale_job_filter = """
      job.status IN ('fetching', 'pre_scanning', 'reviewing', 'judging')
      AND (job.heartbeat_at IS NULL OR NULLIF(job.heartbeat_at, '')::timestamptz < CURRENT_TIMESTAMP - (%s * INTERVAL '1 second'))
      AND mr.id = job.merge_request_id
    """
    conn.execute(
        f"""
        UPDATE review_jobs AS job
        SET status = 'cancelled', locked_at = NULL, locked_by = NULL, heartbeat_at = NULL, updated_at = CURRENT_TIMESTAMP
        FROM merge_requests AS mr
        WHERE {stale_job_filter}
          AND mr.review_status NOT IN ({active_mr_statuses})
        """,
        (reclaim_after_seconds,),
    )
    conn.execute(
        f"""
        UPDATE review_jobs AS job
        SET status = 'queued', locked_at = NULL, locked_by = NULL, heartbeat_at = NULL, updated_at = CURRENT_TIMESTAMP
        FROM merge_requests AS mr
        WHERE {stale_job_filter}
          AND mr.review_status IN ({active_mr_statuses})
        """,
        (reclaim_after_seconds,),
    )
