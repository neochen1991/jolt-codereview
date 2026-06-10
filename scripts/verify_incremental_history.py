from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from orchestration.nodes.finalize import make_finalize_node
from review_runtime import Recorder, load_incremental_context


def create_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE merge_requests (id TEXT PRIMARY KEY, review_status TEXT NOT NULL);
        CREATE TABLE review_jobs (
          id TEXT PRIMARY KEY,
          merge_request_id TEXT NOT NULL,
          head_sha TEXT NOT NULL,
          status TEXT NOT NULL,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE review_runs (
          id TEXT PRIMARY KEY,
          review_job_id TEXT NOT NULL,
          budget_used_json TEXT NOT NULL DEFAULT '{}',
          coverage_json TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL,
          report_summary TEXT,
          completed_at TEXT
        );
        CREATE TABLE review_findings (
          id TEXT PRIMARY KEY,
          review_run_id TEXT NOT NULL,
          dedupe_hash TEXT NOT NULL,
          lifecycle_state TEXT NOT NULL DEFAULT 'pending'
        );
        CREATE TABLE mr_finding_history (
          id TEXT PRIMARY KEY,
          merge_request_id TEXT NOT NULL,
          dedupe_hash TEXT NOT NULL,
          finding_id TEXT,
          first_seen_head_sha TEXT NOT NULL,
          last_seen_head_sha TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          resolved_in_commit TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(merge_request_id, dedupe_hash)
        );
        CREATE TABLE agent_trace_spans (
          id TEXT PRIMARY KEY,
          review_run_id TEXT NOT NULL,
          parent_span_id TEXT,
          span_key TEXT NOT NULL,
          agent_id TEXT,
          status TEXT NOT NULL,
          started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          ended_at TEXT
        );
        CREATE TABLE agent_trace_events (
          id TEXT PRIMARY KEY,
          span_id TEXT NOT NULL,
          event_type TEXT NOT NULL,
          summary TEXT NOT NULL,
          payload_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE llm_call_records (
          id TEXT PRIMARY KEY,
          span_id TEXT NOT NULL,
          provider TEXT NOT NULL,
          model TEXT NOT NULL,
          request_id TEXT,
          prompt_hash TEXT,
          input_tokens INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0,
          duration_ms INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE tool_call_records (
          id TEXT PRIMARY KEY,
          span_id TEXT NOT NULL,
          tool_name TEXT NOT NULL,
          duration_ms INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE tool_observations (
          id TEXT PRIMARY KEY,
          review_run_id TEXT NOT NULL,
          tool_name TEXT NOT NULL,
          rule_id TEXT,
          file_path TEXT NOT NULL,
          line_start INTEGER,
          message TEXT NOT NULL
        );
        """
    )
    return conn


def insert_run(conn: sqlite3.Connection, job_id: str, run_id: str, head_sha: str, hashes: list[str]) -> None:
    conn.execute("INSERT OR IGNORE INTO merge_requests (id, review_status) VALUES ('mr_1', 'queued')")
    conn.execute("INSERT INTO review_jobs (id, merge_request_id, head_sha, status) VALUES (?, 'mr_1', ?, 'running')", (job_id, head_sha))
    conn.execute("INSERT INTO review_runs (id, review_job_id, status) VALUES (?, ?, 'running')", (run_id, job_id))
    for item in hashes:
        conn.execute("INSERT INTO review_findings (id, review_run_id, dedupe_hash) VALUES (?, ?, ?)", (f"finding_{run_id}_{item}", run_id, item))
    conn.commit()


def run_finalize(conn: sqlite3.Connection, job_id: str, run_id: str, head_sha: str, hashes: list[str]) -> None:
    node = make_finalize_node(
        conn=conn,
        job={"id": job_id, "head_sha": head_sha},
        mr={"id": "mr_1"},
        run_id=run_id,
        recorder=Recorder(conn, run_id),
    )
    node(
        {
            "final_findings": [
                {"dedupe_hash": item, "severity": "high", "confidence": 0.9, "file_path": "A.java", "line_start": 1, "title": item}
                for item in hashes
            ],
            "budget_tracker": None,
        }
    )


def main() -> None:
    conn = create_conn()
    insert_run(conn, "job_1", "run_1", "sha_1", ["hash_a", "hash_b"])
    run_finalize(conn, "job_1", "run_1", "sha_1", ["hash_a", "hash_b"])
    before = load_incremental_context(conn, "mr_1", "sha_2")
    insert_run(conn, "job_2", "run_2", "sha_2", ["hash_a"])
    run_finalize(conn, "job_2", "run_2", "sha_2", ["hash_a"])
    rows = [dict(row) for row in conn.execute("SELECT dedupe_hash, status, first_seen_head_sha, last_seen_head_sha, resolved_in_commit FROM mr_finding_history ORDER BY dedupe_hash").fetchall()]
    old_finding = conn.execute("SELECT lifecycle_state FROM review_findings WHERE id = 'finding_run_1_hash_b'").fetchone()["lifecycle_state"]
    assert before["incremental_diff_only"] is True, before
    assert rows == [
        {"dedupe_hash": "hash_a", "status": "active", "first_seen_head_sha": "sha_1", "last_seen_head_sha": "sha_2", "resolved_in_commit": None},
        {"dedupe_hash": "hash_b", "status": "resolved", "first_seen_head_sha": "sha_1", "last_seen_head_sha": "sha_1", "resolved_in_commit": "sha_2"},
    ], rows
    assert old_finding == "resolved", old_finding
    print(json.dumps({"before": before, "history": rows, "resolved_lifecycle_state": old_finding}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
