from __future__ import annotations

import json
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from score_real_pr_reviews import evaluate  # noqa: E402
from review_quality_rollback import request_review_quality_rollback  # noqa: E402


MINIMUM_DISTINCT_MRS = 30


def _text(value: Any) -> str:
    return str(value or "").strip()


def _reviewer(review: dict[str, Any], key: str) -> tuple[str, str]:
    value = review.get(key)
    if isinstance(value, dict):
        return _text(value.get("id") or value.get("identity")), _text(value.get("verdict") or value.get("label"))
    return _text(value), ""


def validate_gold_records(records: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    ids: set[str] = set()
    for index, record in enumerate(records, start=1):
        prefix = _text(record.get("id")) or f"record-{index}"
        if not _text(record.get("id")):
            errors.append(f"{prefix}: id is required")
        elif prefix in ids:
            errors.append(f"{prefix}: duplicate id")
        ids.add(prefix)
        if not _text(record.get("mr_id")):
            errors.append(f"{prefix}: mr_id is required")
        review = record.get("review") if isinstance(record.get("review"), dict) else {}
        reviewer_1, verdict_1 = _reviewer(review, "reviewer_1")
        reviewer_2, verdict_2 = _reviewer(review, "reviewer_2")
        if not reviewer_1 or not reviewer_2:
            errors.append(f"{prefix}: two reviewer identities are required")
        elif reviewer_1 == reviewer_2:
            errors.append(f"{prefix}: distinct reviewer identities are required")
        if _text(review.get("status")) != "approved":
            errors.append(f"{prefix}: review.status must be approved")
        if verdict_1 and verdict_2 and verdict_1 != verdict_2 and not _text(review.get("adjudication_reason")):
            errors.append(f"{prefix}: adjudication_reason is required for reviewer disagreement")
    return errors


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) * percentile + 0.999999)) - 1))
    return ordered[index]


def _summary(engine: str, gold: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> dict[str, Any]:
    findings = [finding for pair in pairs for finding in list(pair.get(f"{engine}_findings") or [])]
    score = evaluate(gold, findings, tolerance=3)
    cross_gold = [record for record in gold if record.get("cross_file") or _text(record.get("evidence_scope")) == "cross_file"]
    cross_score = evaluate(cross_gold, findings, tolerance=3) if cross_gold else None
    tokens = [float(pair[f"{engine}_tokens"]) for pair in pairs]
    durations = [float(pair[f"{engine}_duration_ms"]) for pair in pairs]
    return {
        "engine": engine,
        "sample_count": len(pairs),
        "distinct_mr_count": len({_text(pair.get("merge_request_id")) for pair in pairs if _text(pair.get("merge_request_id"))}),
        "precision": score["precision"],
        "recall": score["recall"],
        "cross_file_recall": cross_score["recall"] if cross_score else None,
        "critical_high_recall": score["high_recall"],
        "negative_false_positive_count": score["negative_false_positive_count"],
        "p95_tokens": _percentile(tokens, 0.95),
        "p95_duration_ms": _percentile(durations, 0.95),
        "matched_count": score["tp"],
        "finding_count": score["finding_count"],
        "missed_gold_ids": score["missed_gold_ids"],
        "labeled_gold_complete": True,
        "paired_cost_complete": True,
    }


def _gate(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(metric: str, passed: bool, actual: Any, required: str) -> None:
        checks.append({"metric": metric, "passed": passed, "actual": actual, "required": required})

    recall_uplift = candidate["recall"] - baseline["recall"]
    cross_uplift = (
        candidate["cross_file_recall"] - baseline["cross_file_recall"]
        if candidate["cross_file_recall"] is not None and baseline["cross_file_recall"] is not None
        else None
    )
    precision_change = candidate["precision"] - baseline["precision"]
    token_ratio = candidate["p95_tokens"] / baseline["p95_tokens"] if baseline["p95_tokens"] else None
    duration_ratio = candidate["p95_duration_ms"] / baseline["p95_duration_ms"] if baseline["p95_duration_ms"] else None
    add("sample_count", candidate["sample_count"] >= MINIMUM_DISTINCT_MRS, candidate["sample_count"], ">=30")
    add("distinct_mr_count", candidate["distinct_mr_count"] >= MINIMUM_DISTINCT_MRS, candidate["distinct_mr_count"], ">=30")
    add("labeled_gold_complete", candidate["labeled_gold_complete"] is True, candidate["labeled_gold_complete"], "true")
    add("paired_cost_complete", candidate["paired_cost_complete"] is True, candidate["paired_cost_complete"], "true")
    add("recall_uplift", recall_uplift >= 0.10, round(recall_uplift, 4), ">=0.10")
    add("cross_file_recall_uplift", cross_uplift is not None and cross_uplift >= 0.15, None if cross_uplift is None else round(cross_uplift, 4), ">=0.15")
    add("critical_high_recall", candidate["critical_high_recall"] >= 0.95, candidate["critical_high_recall"], ">=0.95")
    add("precision_regression", precision_change >= -0.02, round(precision_change, 4), ">=-0.02")
    add("negative_false_positive_count", candidate["negative_false_positive_count"] <= baseline["negative_false_positive_count"], candidate["negative_false_positive_count"], f"<={baseline['negative_false_positive_count']}")
    add("p95_tokens_ratio", token_ratio is not None and token_ratio <= 1.5, token_ratio, "<=1.5")
    add("p95_duration_ratio", duration_ratio is not None and duration_ratio <= 1.5, duration_ratio, "<=1.5")
    return {"version": "review_quality_uplift_v2", "passed": all(check["passed"] for check in checks), "checks": checks}


def evaluate_labeled_pairs(gold: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> dict[str, Any]:
    gold_errors = validate_gold_records(gold)
    gold_mrs = {_text(record.get("mr_id")) for record in gold if _text(record.get("mr_id"))}
    usable_pairs = [pair for pair in pairs if _text(pair.get("merge_request_id")) in gold_mrs]
    paired_mrs = {_text(pair.get("merge_request_id")) for pair in usable_pairs}
    missing_evidence: list[str] = []
    if gold_errors:
        missing_evidence.append("dual_reviewed_gold_complete")
    if not gold:
        missing_evidence.append("dual_reviewed_gold_complete")
    if len(paired_mrs) < MINIMUM_DISTINCT_MRS:
        missing_evidence.append("minimum_30_distinct_paired_mrs")
    cost_keys = ("v1_tokens", "v2_tokens", "v1_duration_ms", "v2_duration_ms")
    costs_complete = bool(usable_pairs) and all(
        key in pair and isinstance(pair.get(key), (int, float)) and float(pair[key]) >= 0
        for pair in usable_pairs
        for key in cost_keys
    )
    if not costs_complete:
        missing_evidence.append("complete_paired_cost_data")
    if missing_evidence:
        return {
            "schema_version": "review_quality_evaluation_v2",
            "validation_status": "provisional",
            "missing_evidence": missing_evidence,
            "gold_validation_errors": gold_errors,
            "gold_record_count": len(gold),
            "distinct_mr_count": len(paired_mrs),
            "paired_run_count": len(usable_pairs),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    baseline = _summary("v1", gold, usable_pairs)
    candidate = _summary("v2", gold, usable_pairs)
    gate = _gate(baseline, candidate)
    return {
        "schema_version": "review_quality_evaluation_v2",
        "validation_status": "verified" if gate["passed"] else "rollback_required",
        "missing_evidence": [],
        "gold_validation_errors": [],
        "gold_record_count": len(gold),
        "distinct_mr_count": len(paired_mrs),
        "paired_run_count": len(usable_pairs),
        "baseline": baseline,
        "candidate": candidate,
        "gate": gate,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _load_findings(conn: Any, run_id: str, merge_request_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, severity, file_path, line_start, line_end, title,
               problem_description, recommendation, evidence,
               covered_rules_json, quality_trace_json, evidence_score_json
        FROM review_findings
        WHERE review_run_id = %s AND selected = 1
        ORDER BY file_path, line_start, id
        """,
        (run_id,),
    ).fetchall()
    findings: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        try:
            covered_rules = json.loads(str(row.pop("covered_rules_json") or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            covered_rules = []
        findings.append({
            **row,
            "mr_id": merge_request_id,
            "covered_rules": covered_rules,
            "quality_trace": _json_dict(row.pop("quality_trace_json", "{}")),
            "evidence_score": _json_dict(row.pop("evidence_score_json", "{}")),
        })
    return findings


def _load_completed_pairs(conn: Any, project_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT p.merge_request_id, p.production_run_id, p.baseline_run_id,
               COALESCE(pr.budget_used_json, '{}') AS v2_budget_json,
               COALESCE(br.budget_used_json, '{}') AS v1_budget_json,
               CAST(EXTRACT(EPOCH FROM (pr.completed_at::timestamptz - pr.started_at::timestamptz)) * 1000 AS BIGINT) AS v2_duration_ms,
               CAST(EXTRACT(EPOCH FROM (br.completed_at::timestamptz - br.started_at::timestamptz)) * 1000 AS BIGINT) AS v1_duration_ms
        FROM review_quality_shadow_pairs p
        JOIN review_runs pr ON pr.id = p.production_run_id
        JOIN review_runs br ON br.id = p.baseline_run_id
        WHERE p.project_id = %s AND p.status = 'completed'
        ORDER BY p.created_at
        """,
        (project_id,),
    ).fetchall()
    pairs: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        v1_budget = _json_dict(row.get("v1_budget_json"))
        v2_budget = _json_dict(row.get("v2_budget_json"))
        mr_id = _text(row.get("merge_request_id"))
        v1_run_id = _text(row.get("baseline_run_id"))
        v2_run_id = _text(row.get("production_run_id"))
        pairs.append({
            "merge_request_id": mr_id,
            "v1_findings": _load_findings(conn, v1_run_id, mr_id),
            "v2_findings": _load_findings(conn, v2_run_id, mr_id),
            "v1_tokens": int(v1_budget.get("input_tokens") or 0) + int(v1_budget.get("output_tokens") or 0),
            "v2_tokens": int(v2_budget.get("input_tokens") or 0) + int(v2_budget.get("output_tokens") or 0),
            "v1_duration_ms": row.get("v1_duration_ms"),
            "v2_duration_ms": row.get("v2_duration_ms"),
        })
    return pairs


def evaluate_project_labeled_quality(
    conn: Any,
    config: dict[str, Any],
    project_id: str,
    source_run_id: str,
) -> dict[str, Any]:
    try:
        quality = config.get("review_quality") if isinstance(config.get("review_quality"), dict) else {}
        configured_path = Path(_text(quality.get("gold_dataset_path")) or "evaluation/production_review_quality_gold.jsonl")
        gold_path = configured_path if configured_path.is_absolute() else REPO_ROOT / configured_path
        if gold_path.exists():
            gold = [json.loads(line) for line in gold_path.read_text("utf-8").splitlines() if line.strip()]
        else:
            gold = []
        report = evaluate_labeled_pairs(gold, _load_completed_pairs(conn, project_id))
        report["project_id"] = project_id
        report["gold_dataset_path"] = str(gold_path)
        stable_report = {key: value for key, value in report.items() if key != "generated_at"}
        report_id = "quality_eval_" + hashlib.sha256(
            json.dumps({"project_id": project_id, "report": stable_report}, sort_keys=True).encode("utf-8")
        ).hexdigest()[:28]
        conn.execute(
            """
            INSERT INTO evaluation_reports (id, project_id, report_json)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (report_id, project_id, json.dumps(report, ensure_ascii=False)),
        )
        conn.commit()
        if report["validation_status"] == "rollback_required":
            try:
                rollback = request_review_quality_rollback(
                    conn,
                    config,
                    project_id,
                    trigger="labeled_quality_gate_failed",
                    source_run_id=source_run_id,
                    evidence={"evaluation_report_id": report_id, "gate": report.get("gate")},
                )
                report["rollback"] = rollback
            except Exception as exc:
                report["rollback"] = {"status": "rollback_pending", "error_message": str(exc)}
        return report
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"validation_status": "evaluator_error", "error_message": str(exc), "project_id": project_id}
