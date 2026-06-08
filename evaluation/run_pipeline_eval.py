from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def load_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except json.JSONDecodeError:
        return fallback


def normalize_rule(rule: Any) -> str:
    return str(rule or "").strip()


def evaluate_mr(conn: sqlite3.Connection, mr_id: str) -> dict[str, Any]:
    conn.row_factory = sqlite3.Row
    mr = conn.execute("SELECT * FROM merge_requests WHERE id = ?", (mr_id,)).fetchone()
    if not mr:
        raise SystemExit(f"MR not found: {mr_id}")
    metadata = load_json(mr["metadata_json"], {})
    expected = {normalize_rule(item) for item in metadata.get("expected_issues", []) if normalize_rule(item)}
    run = conn.execute(
        """
        SELECT rr.*
        FROM review_runs rr
        JOIN review_jobs rj ON rj.id = rr.review_job_id
        WHERE rj.merge_request_id = ?
        ORDER BY rr.started_at DESC
        LIMIT 1
        """,
        (mr_id,),
    ).fetchone()
    if not run:
        raise SystemExit(f"MR has no review run: {mr_id}")
    findings = conn.execute(
        """
        SELECT *
        FROM review_findings
        WHERE review_run_id = ?
        ORDER BY selected DESC, severity DESC, confidence DESC, created_at
        """,
        (run["id"],),
    ).fetchall()
    covered_rules: set[str] = set()
    final_findings = []
    for finding in findings:
        rules = [normalize_rule(item) for item in load_json(finding["covered_rules_json"], []) if normalize_rule(item)]
        covered_rules.update(rules)
        final_findings.append(
            {
                "id": finding["id"],
                "agent_id": finding["agent_id"],
                "severity": finding["severity"],
                "confidence": finding["confidence"],
                "title": finding["title"],
                "file_path": finding["file_path"],
                "line_start": finding["line_start"],
                "covered_rules": rules,
            }
        )
    matched = sorted(rule for rule in expected if rule in covered_rules)
    missing = sorted(rule for rule in expected if rule not in covered_rules)
    unknown = [finding for finding in final_findings if not any(rule in expected for rule in finding["covered_rules"])]
    top5_rules = []
    for finding in final_findings[:5]:
        top5_rules.extend(rule for rule in finding["covered_rules"] if rule)
    agreement_at_5 = len({rule for rule in top5_rules if rule in expected}) / min(5, len(expected) or 5)
    precision = len(matched) / (len(matched) + len(unknown)) if matched or unknown else 1.0
    recall = len(matched) / len(expected) if expected else 1.0
    return {
        "mr_id": mr_id,
        "run_id": run["id"],
        "expected_count": len(expected),
        "finding_count": len(final_findings),
        "matched_count": len(matched),
        "missing_count": len(missing),
        "false_positive_count": len(unknown),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "fp_rate": round(len(unknown) / len(final_findings), 4) if final_findings else 0.0,
        "agreement_at_5": round(agreement_at_5, 4),
        "matched": matched,
        "missing": missing,
        "unknown_findings": unknown,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--mr-id", required=True)
    parser.add_argument("--negative", default="")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    report = evaluate_mr(conn, args.mr_id)
    negative_items = []
    if args.negative:
        negative_path = Path(args.negative)
        if negative_path.exists():
            for line in negative_path.read_text("utf-8").splitlines():
                if line.strip():
                    negative_items.append(json.loads(line))
    report["negative_gold_count"] = len(negative_items)
    report["negative_gold_set"] = negative_items
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
