from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from db_compat import open_app_database  # noqa: E402
from review_runtime import choose_job  # noqa: E402


config_path = os.environ.get("PG_RUNTIME_CONFIG_PATH") or os.environ.get("CONFIG_PATH")
if not config_path:
    raise RuntimeError("Set CONFIG_PATH or PG_RUNTIME_CONFIG_PATH to a PostgreSQL config before running verify_pg_project_concurrency_lock.py")

config = json.loads(Path(config_path).read_text(encoding="utf-8"))
driver = str((config.get("server") or {}).get("database_driver") or "")
if driver != "postgres":
    raise RuntimeError("verify_pg_project_concurrency_lock.py requires server.database_driver=postgres")

suffix = f"{int(time.time() * 1000)}_{os.getpid()}"
project_id = f"pg_lock_project_{suffix}"
repo_id = f"pg_lock_repo_{suffix}"
mr_ids = [f"pg_lock_mr_{suffix}_1", f"pg_lock_mr_{suffix}_2"]
job_ids = [f"pg_lock_job_{suffix}_1", f"pg_lock_job_{suffix}_2"]


def seed() -> None:
    conn = open_app_database(config)
    try:
        conn.execute("INSERT INTO projects (id, name, description) VALUES (?, ?, ?)", (project_id, "PG Lock Project", "verify project claim lock"))
        conn.execute(
            "INSERT INTO project_settings (id, project_id, settings_key, settings_json) VALUES (?, ?, 'queue_policy', ?)",
            (f"pg_lock_setting_{suffix}", project_id, json.dumps({"max_concurrency": 1})),
        )
        conn.execute(
            """
            INSERT INTO repositories (
              id, project_id, provider, external_repo_id, name, default_branch, status, provider_config_json
            )
            VALUES (?, ?, 'github', ?, 'pg-lock-repo', 'main', 'active', '{}')
            """,
            (repo_id, project_id, f"pg-lock/{suffix}"),
        )
        for index, mr_id in enumerate(mr_ids, start=1):
            conn.execute(
                """
                INSERT INTO merge_requests (
                  id, repository_id, external_mr_id, number, title, author, source_branch, target_branch,
                  review_status, risk_score, latest_head_sha, html_url, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, 'pg-lock', 'feature', 'main', 'queued', 10, ?, '', '{}')
                """,
                (mr_id, repo_id, f"mr-{index}", index, f"PG lock MR {index}", f"sha-{suffix}-{index}"),
            )
            conn.execute(
                """
                INSERT INTO review_jobs (id, merge_request_id, head_sha, status, priority, requested_effort_level)
                VALUES (?, ?, ?, 'queued', ?, 'standard')
                """,
                (job_ids[index - 1], mr_id, f"sha-{suffix}-{index}", 100 - index),
            )
        conn.commit()
    finally:
        conn.close()


def claim(barrier: threading.Barrier, results: list[dict[str, Any] | None], index: int) -> None:
    conn = open_app_database(config)
    try:
        barrier.wait(timeout=10)
        job = choose_job(conn, config)
        results[index] = dict(job) if job else None
    finally:
        conn.close()


seed()
barrier = threading.Barrier(2)
results: list[dict[str, Any] | None] = [None, None]
threads = [threading.Thread(target=claim, args=(barrier, results, index)) for index in range(2)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join(timeout=20)

if any(thread.is_alive() for thread in threads):
    raise AssertionError("PG project concurrency lock verification timed out")

conn = open_app_database(config)
try:
    rows = conn.execute(
        """
        SELECT id, status
        FROM review_jobs
        WHERE id IN (?, ?)
        ORDER BY id
        """,
        tuple(job_ids),
    ).fetchall()
finally:
    conn.close()

claimed_ids = sorted(result["id"] for result in results if result)
claimed_test_ids = [job_id for job_id in claimed_ids if job_id in set(job_ids)]
fetching_count = sum(1 for row in rows if row["status"] == "fetching")
queued_count = sum(1 for row in rows if row["status"] == "queued")

if len(claimed_test_ids) != 1 or fetching_count != 1 or queued_count != 1:
    raise AssertionError(
        json.dumps(
            {
                "claimed_ids": claimed_ids,
                "claimed_test_ids": claimed_test_ids,
                "rows": [dict(row) for row in rows],
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

print("PG project concurrency lock checks passed.")
