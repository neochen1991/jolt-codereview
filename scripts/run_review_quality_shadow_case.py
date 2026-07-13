from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mr-backend/worker"))
sys.path.insert(0, str(ROOT / "scripts"))

from quality_shadow import load_shadow_input_artifact
from score_real_pr_reviews import evaluate, gold_id


SUCCESS_STATUSES = {"waiting_confirmation", "no_issue"}
FAILURE_STATUSES = {"failed", "dead_letter", "cancelled", "too_large", "superseded"}
SHADOW_KINDS = {"quality_shadow_v1": "v1", "quality_shadow_v2": "v2"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def gold_records_sha256(case: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(case.get("gold_records") or [], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def validate_case(value: dict[str, Any]) -> dict[str, Any]:
    case = dict(value)
    for field in ("case_id", "merge_request_id", "head_sha", "input_snapshot_id", "input_artifact_sha256"):
        if not _text(case.get(field)):
            raise ValueError(f"Shadow case requires {field}")
    kind = _text(case.get("execution_kind"))
    if kind not in SHADOW_KINDS:
        raise ValueError("Shadow case execution_kind must be quality_shadow_v1 or quality_shadow_v2")
    if not isinstance(case.get("gold_records"), list):
        raise ValueError("Shadow case requires gold_records")
    if any(not isinstance(item, dict) or not _text(item.get("id")) for item in case["gold_records"]):
        raise ValueError("Shadow case gold_records require a stable id")
    digest = _text(case.get("input_artifact_sha256")).lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("Shadow case input_artifact_sha256 must be a 64-character hex digest")
    case["input_artifact_sha256"] = digest
    case["context_engine"] = SHADOW_KINDS[kind]
    return case


def build_job_id(case: dict[str, Any]) -> str:
    identity = "|".join(
        [
            _text(case.get("case_id")),
            _text(case.get("merge_request_id")),
            _text(case.get("head_sha")),
            _text(case.get("input_snapshot_id")),
            _text(case.get("input_artifact_sha256")),
            _text(case.get("execution_kind")),
            gold_records_sha256(case),
        ]
    )
    return f"shadow_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:32]}"


def shadow_job_context(case: dict[str, Any]) -> dict[str, Any]:
    gold_digest = gold_records_sha256(case)
    return {
        "kind": "review_quality_shadow",
        "case_id": _text(case.get("case_id")),
        "input_snapshot_id": _text(case.get("input_snapshot_id")),
        "input_artifact_sha256": _text(case.get("input_artifact_sha256")),
        "gold_sha256": gold_digest,
        "publish_allowed": False,
    }


def enqueue_shadow_job(conn: Any, case: dict[str, Any]) -> str:
    job_id = build_job_id(case)
    context_json = json.dumps(shadow_job_context(case), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    conn.execute(
        """
        INSERT INTO review_jobs (
          id, merge_request_id, head_sha, status, priority,
          requested_effort_level, requested_by, debug_context_json, execution_kind
        ) VALUES (%s, %s, %s, 'queued', -100, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (
            job_id,
            _text(case.get("merge_request_id")),
            _text(case.get("head_sha")),
            _text(case.get("requested_effort_level") or "standard"),
            _text(case.get("requested_by") or "review-quality-shadow"),
            context_json,
            _text(case.get("execution_kind")),
        ),
    )
    conn.commit()
    return job_id


def _positive_gold(case: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in case.get("gold_records") or []
        if isinstance(item, dict) and _text(item.get("ground_truth") or "true_positive") != "negative"
    ]


def score_shadow_findings(case: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, int]:
    report = evaluate(list(case.get("gold_records") or []), findings, int(case.get("line_tolerance") or 3))
    missed = {_text(item) for item in report.get("missed_gold_ids") or []}
    positive = _positive_gold(case)
    cross_file = [
        item
        for item in positive
        if bool(item.get("cross_file")) or _text(item.get("evidence_scope")) == "cross_file"
    ]
    critical_high = [item for item in positive if _text(item.get("severity")).lower() in {"critical", "high"}]
    matched = lambda rows: sum(1 for item in rows if gold_id(item) not in missed)
    return {
        "expected_count": len(positive),
        "true_positive_count": int(report.get("tp") or 0),
        "cross_file_expected_count": len(cross_file),
        "cross_file_true_positive_count": matched(cross_file),
        "critical_high_expected_count": len(critical_high),
        "critical_high_true_positive_count": matched(critical_high),
        "negative_false_positive_count": int(report.get("negative_false_positive_count") or 0),
    }


def _json_record(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def build_shadow_result(
    case: dict[str, Any],
    run: dict[str, Any],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    budget = _json_record(run.get("budget_used_json"))
    score = score_shadow_findings(case, findings)
    return {
        "case_id": _text(case.get("case_id")),
        "review_job_id": build_job_id(case),
        "review_run_id": _text(run.get("id")),
        "execution_kind": _text(case.get("execution_kind")),
        "context_engine": _text(case.get("context_engine")),
        "input_snapshot_id": _text(case.get("input_snapshot_id")),
        "input_artifact_sha256": _text(case.get("input_artifact_sha256")),
        "status": _text(run.get("status")),
        **score,
        "finding_count": len(findings),
        "tokens": int(budget.get("input_tokens") or 0) + int(budget.get("output_tokens") or 0),
        "duration_ms": int(run.get("duration_ms") or 0),
        "publish_attempt_count": 0,
    }


def wait_for_terminal_run(conn: Any, job_id: str, timeout_seconds: int, poll_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + max(1, timeout_seconds)
    while time.monotonic() < deadline:
        job = conn.execute("SELECT status, execution_kind FROM review_jobs WHERE id = %s", (job_id,)).fetchone()
        if not job:
            raise RuntimeError(f"Shadow job disappeared: {job_id}")
        status = _text(job["status"])
        if status in FAILURE_STATUSES:
            raise RuntimeError(f"Shadow job {job_id} ended with {status}")
        if status in SUCCESS_STATUSES:
            run = conn.execute(
                """
                SELECT rr.*,
                       CAST(EXTRACT(EPOCH FROM (rr.completed_at::timestamptz - rr.started_at::timestamptz)) * 1000 AS BIGINT) AS duration_ms
                FROM review_runs rr
                WHERE rr.review_job_id = %s
                ORDER BY rr.started_at DESC
                LIMIT 1
                """,
                (job_id,),
            ).fetchone()
            if run and _text(run["status"]) in SUCCESS_STATUSES:
                return dict(run)
        time.sleep(max(0.05, poll_seconds))
    raise TimeoutError(f"Shadow job {job_id} did not finish within {timeout_seconds}s; ensure the Review Worker is running")


def load_findings(conn: Any, run_id: str, merge_request_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, severity, confidence, agent_id, dedupe_hash, file_path,
               line_start, line_end, title, problem_description, recommendation,
               evidence, covered_rules_json, quality_trace_json, evidence_score_json
        FROM review_findings
        WHERE review_run_id = %s AND selected = 1
        ORDER BY file_path, line_start, id
        """,
        (run_id,),
    ).fetchall()
    findings: list[dict[str, Any]] = []
    for row_value in rows:
        row = dict(row_value)
        covered_rules = json.loads(str(row.pop("covered_rules_json") or "[]"))
        quality_trace = _json_record(row.pop("quality_trace_json", "{}"))
        evidence_score = _json_record(row.pop("evidence_score_json", "{}"))
        findings.append(
            {
                **row,
                "mr_id": merge_request_id,
                "covered_rules": covered_rules,
                "quality_trace": quality_trace,
                "evidence_score": evidence_score,
            }
        )
    return findings


def run_case(conn: Any, raw_case: dict[str, Any], timeout_seconds: int, poll_seconds: float) -> dict[str, Any]:
    case = validate_case(raw_case)
    load_shadow_input_artifact(
        conn,
        {
            "execution_kind": case["execution_kind"],
            "merge_request_id": case["merge_request_id"],
            "head_sha": case["head_sha"],
            "debug_context_json": json.dumps(shadow_job_context(case)),
        },
    )
    job_id = enqueue_shadow_job(conn, case)
    run = wait_for_terminal_run(conn, job_id, timeout_seconds, poll_seconds)
    findings = load_findings(conn, _text(run.get("id")), _text(case.get("merge_request_id")))
    return build_shadow_result(case, run, findings)


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid Shadow case JSON: {exc}") from exc
    database_url = _text(os.environ.get("DATABASE_URL"))
    if not database_url:
        raise SystemExit("DATABASE_URL is required for the native Review Quality Shadow runner")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise SystemExit("psycopg is required; use mr-backend/.venv/bin/python") from exc
    timeout_seconds = int(os.environ.get("JOLT_SHADOW_TIMEOUT_SECONDS") or 1800)
    poll_seconds = float(os.environ.get("JOLT_SHADOW_POLL_SECONDS") or 1)
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        result = run_case(conn, payload, timeout_seconds, poll_seconds)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
