from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "worker"
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from llm.client import parse_llm_findings
from review_runtime import ensure_worker_schema
from tools.candidate_store import upsert_candidate_finding


def main() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE review_runs (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE review_findings (id TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO review_runs (id) VALUES ('run_candidate_verify')")
    conn.execute("INSERT INTO review_findings (id) VALUES ('finding_final')")
    ensure_worker_schema(conn)

    candidate = {
        "agent_id": "security_agent",
        "dedupe_hash": "hash_authz",
        "severity": "high",
        "confidence": 0.91,
        "file_path": "src/main/java/demo/PaymentController.java",
        "line_start": 42,
        "line_end": 42,
        "title": "接口缺少资源归属校验",
        "problem_description": "merchantId 来自请求但没有校验归属。",
        "evidence": "merchantId",
        "covered_rules": ["SEC-AUTHZ-002"],
    }
    upsert_candidate_finding(
        conn,
        review_run_id="run_candidate_verify",
        item=candidate,
        stage="verifier",
        status="accepted",
    )
    upsert_candidate_finding(
        conn,
        review_run_id="run_candidate_verify",
        item={**candidate, "confidence": 0.2, "rejected_reasons": ["below_confidence"]},
        stage="judge",
        status="rejected",
        rejected_reasons=["below_confidence"],
    )
    upsert_candidate_finding(
        conn,
        review_run_id="run_candidate_verify",
        item=candidate,
        stage="judge",
        status="final",
        final_finding_id="finding_final",
    )

    rows = conn.execute(
        "SELECT stage, status, rejected_reasons_json, final_finding_id FROM candidate_findings ORDER BY stage, status"
    ).fetchall()
    assert len(rows) == 2, [dict(row) for row in rows]
    by_stage = {row["stage"]: row for row in rows}
    assert by_stage["verifier"]["status"] == "accepted"
    assert by_stage["judge"]["status"] == "final"
    assert by_stage["judge"]["final_finding_id"] == "finding_final"

    rejected_json = conn.execute(
        "SELECT rejected_reasons_json FROM candidate_findings WHERE stage = 'judge'"
    ).fetchone()["rejected_reasons_json"]
    assert json.loads(rejected_json) in ([], ["below_confidence"])

    files = [SimpleNamespace(filename="src/main/java/demo/PaymentController.java")]
    payload = [
        {
            "severity": "medium",
            "confidence": 0.8,
            "file_path": "src/main/java/demo/PaymentController.java",
            "line_start": index + 1,
            "line_end": index + 1,
            "title": f"候选问题 {index}",
            "problem_description": "x",
            "recommendation": "x",
            "suggested_code": "return;",
            "evidence": "return;",
        }
        for index in range(12)
    ]
    parsed = parse_llm_findings("coding_agent", json.dumps(payload, ensure_ascii=False), files, max_findings=12)
    assert len(parsed) == 12, len(parsed)

    print(
        json.dumps(
            {
                "candidate_rows": len(rows),
                "judge_status": by_stage["judge"]["status"],
                "parse_llm_findings_count": len(parsed),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
