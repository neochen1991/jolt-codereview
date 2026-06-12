from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from review_runtime import choose_job, lock_project_claim_if_needed  # noqa: E402


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE project_settings (
          id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL,
          settings_key TEXT NOT NULL,
          settings_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE repositories (
          id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL
        );

        CREATE TABLE merge_requests (
          id TEXT PRIMARY KEY,
          repository_id TEXT NOT NULL,
          review_status TEXT NOT NULL
        );

        CREATE TABLE review_jobs (
          id TEXT PRIMARY KEY,
          merge_request_id TEXT NOT NULL,
          head_sha TEXT NOT NULL,
          status TEXT NOT NULL,
          priority INTEGER NOT NULL DEFAULT 0,
          requested_effort_level TEXT NOT NULL DEFAULT 'standard',
          requested_by TEXT,
          attempt INTEGER NOT NULL DEFAULT 0,
          locked_at TEXT,
          locked_by TEXT,
          heartbeat_at TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    return conn


def seed_project(conn: sqlite3.Connection, project_id: str, max_concurrency: int) -> None:
    conn.execute(
        "INSERT INTO project_settings (id, project_id, settings_key, settings_json) VALUES (?, ?, 'queue_policy', ?)",
        (f"setting_{project_id}", project_id, json.dumps({"max_concurrency": max_concurrency})),
    )
    conn.execute("INSERT INTO repositories (id, project_id) VALUES (?, ?)", (f"repo_{project_id}", project_id))


def seed_job(conn: sqlite3.Connection, project_id: str, suffix: str, priority: int) -> None:
    mr_id = f"mr_{project_id}_{suffix}"
    job_id = f"job_{project_id}_{suffix}"
    conn.execute(
        "INSERT INTO merge_requests (id, repository_id, review_status) VALUES (?, ?, 'queued')",
        (mr_id, f"repo_{project_id}"),
    )
    conn.execute(
        """
        INSERT INTO review_jobs (id, merge_request_id, head_sha, status, priority, requested_effort_level)
        VALUES (?, ?, ?, 'queued', ?, 'standard')
        """,
        (job_id, mr_id, f"sha_{project_id}_{suffix}", priority),
    )


def status(conn: sqlite3.Connection, job_id: str) -> str:
    return conn.execute("SELECT status FROM review_jobs WHERE id = ?", (job_id,)).fetchone()["status"]


base_config = {"queue_policy": {"max_concurrency": 1}}

conn = connect()
seed_project(conn, "a", 1)
seed_project(conn, "b", 1)
seed_job(conn, "a", "1", 100)
seed_job(conn, "a", "2", 90)
seed_job(conn, "b", "1", 80)
conn.commit()

first = choose_job(conn, base_config)
assert first and first["id"] == "job_a_1", first
second = choose_job(conn, base_config)
assert second and second["id"] == "job_b_1", second
assert status(conn, "job_a_2") == "queued", "project a should be capped at one active job"

conn.execute(
    "UPDATE project_settings SET settings_json = ? WHERE project_id = 'a' AND settings_key = 'queue_policy'",
    (json.dumps({"max_concurrency": 2}),),
)
conn.commit()
third = choose_job(conn, base_config)
assert third and third["id"] == "job_a_2", third
assert status(conn, "job_a_2") == "fetching", "project a should allow a second active job after raising max_concurrency"
conn.close()


class RecordingPostgresLikeConnection:
    dialect = "postgres"

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def execute(self, sql: str, params: tuple[str, ...]):
        self.calls.append((sql, params))
        return None


recording_conn = RecordingPostgresLikeConnection()
lock_project_claim_if_needed(recording_conn, "project_a")
assert recording_conn.calls == [
    ("SELECT pg_advisory_xact_lock(hashtext(?)::bigint)", ("jolt-review-project:project_a",))
]

print("Worker project concurrency checks passed.")
