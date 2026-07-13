from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
WORKER_ROOT = ROOT / "mr-backend" / "worker"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(WORKER_ROOT))

from compare_review_quality_runs import compare_worker_runs  # noqa: E402
from config import load_config  # noqa: E402
from db_postgres import open_app_database  # noqa: E402


def _json_value(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _reason_codes(value: Any) -> list[str]:
    result: list[str] = []
    for item in _json_value(value, []):
        code = item.get("code") if isinstance(item, dict) else item
        text = str(code or "").strip()
        if text and text not in result:
            result.append(text)
    return sorted(result)


def _collect_context_hashes(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"context_hash", "context_plan_hash"} and str(child or "").strip():
                result.add(str(child).strip())
            else:
                result.update(_collect_context_hashes(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_collect_context_hashes(child))
    return result


def snapshot_from_rows(
    *,
    run: dict[str, Any],
    candidates: Iterable[dict[str, Any]],
    findings: Iterable[dict[str, Any]],
    llm_calls: Iterable[dict[str, Any]],
    artifacts: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    candidate_ids: list[str] = []
    decision_reasons: dict[str, list[str]] = {}
    for row in candidates:
        stable_id = "|".join([str(row.get("dedupe_hash") or ""), str(row.get("stage") or "")])
        candidate_ids.append(stable_id)
        decision_reasons[stable_id] = _reason_codes(row.get("decision_reason_json"))

    normalized_findings = sorted(
        [
            {
                "finding_id": str(row.get("dedupe_hash") or row.get("finding_id") or row.get("id") or ""),
                "severity": str(row.get("severity") or ""),
            }
            for row in findings
        ],
        key=lambda item: item["finding_id"],
    )
    llm_fingerprints = sorted(
        "|".join(
            [
                str(row.get("span_key") or row.get("operation") or ""),
                str(row.get("provider") or ""),
                str(row.get("model") or ""),
                str(row.get("prompt_hash") or ""),
                str(row.get("response_hash") or ""),
            ]
        )
        for row in llm_calls
    )
    artifact_rows = list(artifacts)
    artifact_hashes = sorted({str(row.get("sha256") or "") for row in artifact_rows if str(row.get("sha256") or "")})
    context_hashes = _collect_context_hashes(_json_value(run.get("coverage_json"), {}))
    for row in artifact_rows:
        context_hashes.update(_collect_context_hashes(_json_value(row.get("metadata_json"), {})))

    return {
        "run_id": str(run.get("id") or ""),
        "candidate_ids": sorted(candidate_ids),
        "findings": normalized_findings,
        "decision_reasons": dict(sorted(decision_reasons.items())),
        "context_hashes": sorted(context_hashes),
        "llm_fingerprints": llm_fingerprints,
        "artifact_hashes": artifact_hashes,
    }


def load_run_snapshot(conn: Any, run_id: str) -> dict[str, Any]:
    run = conn.execute("SELECT id, coverage_json FROM review_runs WHERE id = %s", (run_id,)).fetchone()
    if not run:
        raise ValueError(f"review run not found: {run_id}")
    candidates = conn.execute(
        "SELECT dedupe_hash, stage, decision_reason_json FROM candidate_findings WHERE review_run_id = %s ORDER BY dedupe_hash, stage",
        (run_id,),
    ).fetchall()
    findings = conn.execute(
        "SELECT dedupe_hash, severity FROM review_findings WHERE review_run_id = %s ORDER BY dedupe_hash",
        (run_id,),
    ).fetchall()
    llm_calls = conn.execute(
        """
        SELECT l.*, s.span_key
        FROM llm_call_records l
        JOIN agent_trace_spans s ON s.id = l.span_id
        WHERE s.review_run_id = %s
        ORDER BY s.span_key, l.created_at
        """,
        (run_id,),
    ).fetchall()
    artifacts = conn.execute(
        "SELECT sha256, metadata_json FROM review_artifacts WHERE review_run_id = %s ORDER BY created_at",
        (run_id,),
    ).fetchall()
    return snapshot_from_rows(
        run=dict(run),
        candidates=[dict(row) for row in candidates],
        findings=[dict(row) for row in findings],
        llm_calls=[dict(row) for row in llm_calls],
        artifacts=[dict(row) for row in artifacts],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two completed Review Worker runs.")
    parser.add_argument("--baseline-run", required=True)
    parser.add_argument("--repeated-run", required=True)
    parser.add_argument("--out")
    parser.add_argument("--snapshot-dir")
    args = parser.parse_args()

    conn = open_app_database(load_config())
    try:
        baseline = load_run_snapshot(conn, args.baseline_run)
        repeated = load_run_snapshot(conn, args.repeated_run)
    finally:
        conn.close()

    if args.snapshot_dir:
        snapshot_dir = Path(args.snapshot_dir)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        (snapshot_dir / f"{args.baseline_run}.json").write_text(
            json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (snapshot_dir / f"{args.repeated_run}.json").write_text(
            json.dumps(repeated, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    report = compare_worker_runs(baseline, repeated)
    report.update({"baseline_run_id": args.baseline_run, "repeated_run_id": args.repeated_run})
    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(output + "\n", encoding="utf-8")
    print(output)
    if not report["exact_match"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
