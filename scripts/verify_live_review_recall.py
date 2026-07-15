from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


HIGH_SEVERITIES = {"critical", "high"}
SOFT_REJECTION_REASONS = {
    "bound_checkpoint_mismatch",
    "bound_required_evidence_incomplete",
    "bound_rule_mismatch",
    "evidence_contract_not_satisfied",
    "evidence_score_below_drop_threshold",
    "not_selected_after_quality_calibration",
    "secondary_test_advisory",
    "unsupported_bound_claim",
    "unsupported_low_precision_llm_finding",
}


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None or value == "":
        return []
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        return decoded if isinstance(decoded, list) else [decoded]
    return [value]


def _ids(item: dict[str, Any]) -> set[str]:
    values: list[Any] = []
    for key in ("rule_id", "matched_rule_id", "covered_rules", "covered_rule_ids", "rule_ids"):
        values.extend(_list(item.get(key)))
    return {str(value).strip() for value in values if str(value).strip()}


def _path(item: dict[str, Any]) -> str:
    return str(item.get("file_path") or item.get("path") or "").replace("\\", "/").lstrip("./")


def _line(item: dict[str, Any]) -> int:
    try:
        return int(item.get("line_start") or item.get("line") or 0)
    except (TypeError, ValueError):
        return 0


def _identifier(item: dict[str, Any], fallback: str) -> str:
    return str(item.get("finding_id") or item.get("candidate_id") or item.get("id") or item.get("dedupe_hash") or fallback)


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    for key in ("payload", "details", "data", "metadata"):
        value = event.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict):
                return decoded
    return {}


def _event_type(event: dict[str, Any]) -> str:
    return str(event.get("event_type") or event.get("type") or event.get("name") or "")


def _matches_gold(gold: dict[str, Any], finding: dict[str, Any], *, line_tolerance: int) -> bool:
    gold_rules = _ids(gold)
    finding_rules = _ids(finding)
    if gold_rules and not gold_rules.intersection(finding_rules):
        return False
    gold_path = _path(gold)
    finding_path = _path(finding)
    if gold_path and finding_path and gold_path != finding_path:
        return False
    gold_line = _line(gold)
    finding_line = _line(finding)
    return not (gold_line and finding_line) or abs(gold_line - finding_line) <= line_tolerance


def _context_skip_matches(gold: dict[str, Any], event: dict[str, Any]) -> bool:
    payload = _payload(event)
    event_rules = _ids(payload)
    gold_rules = _ids(gold)
    if gold_rules and event_rules and gold_rules.intersection(event_rules):
        return True
    selected_files = {_path({"file_path": value}) for value in _list(payload.get("selected_files"))}
    return bool(_path(gold) and _path(gold) in selected_files)


def _fallback_size(event: dict[str, Any]) -> int:
    payload = _payload(event)
    try:
        return int(payload.get("after"))
    except (TypeError, ValueError):
        return len(_list(payload.get("selected_files")))


def evaluate_live_review_recall(report: dict[str, Any], *, line_tolerance: int = 5) -> dict[str, Any]:
    run_id = str(report.get("run_id") or "").strip()
    gold_findings = [item for item in _list(report.get("gold_findings")) if isinstance(item, dict)]
    final_findings = [item for item in _list(report.get("final_findings")) if isinstance(item, dict)]
    events = [item for item in _list(report.get("events")) if isinstance(item, dict)]
    decisions = [item for item in _list(report.get("candidate_decisions")) if isinstance(item, dict)]
    failures: list[dict[str, Any]] = []

    if not run_id:
        failures.append({"code": "missing_live_run_id"})
    if not gold_findings:
        failures.append({"code": "missing_gold_findings"})
    if not events:
        failures.append({"code": "missing_live_run_events"})

    matched_gold_count = 0
    context_skips = [event for event in events if _event_type(event) == "no_relevant_context_units"]
    for index, gold in enumerate(gold_findings):
        if any(_matches_gold(gold, finding, line_tolerance=line_tolerance) for finding in final_findings):
            matched_gold_count += 1
            continue
        gold_id = _identifier(gold, f"gold-{index + 1}")
        if any(_context_skip_matches(gold, event) for event in context_skips):
            failures.append({"code": "gold_lost_at_context", "gold_id": gold_id, "rule_ids": sorted(_ids(gold))})
        else:
            failures.append({"code": "gold_not_recalled", "gold_id": gold_id, "rule_ids": sorted(_ids(gold))})

    fallback_sizes = [_fallback_size(event) for event in events if _event_type(event) == "context_units_fallback"]
    fallback_max_units = max(fallback_sizes, default=0)
    if fallback_max_units > 3:
        failures.append({"code": "unbounded_context_fallback", "selected_unit_count": fallback_max_units, "maximum": 3})

    for index, decision in enumerate(decisions):
        if str(decision.get("status") or "").lower() != "rejected":
            continue
        reasons = {str(value) for value in _list(decision.get("rejected_reasons") or decision.get("rejected_reasons_json"))}
        candidate_id = _identifier(decision, f"candidate-{index + 1}")
        if "judge_unclassified_rejection" in reasons:
            failures.append({"code": "judge_unclassified_rejection", "candidate_id": candidate_id})
        soft_reasons = sorted(reasons.intersection(SOFT_REJECTION_REASONS))
        if str(decision.get("severity") or "").lower() in HIGH_SEVERITIES and soft_reasons:
            failures.append(
                {
                    "code": "high_severity_soft_rejection",
                    "candidate_id": candidate_id,
                    "severity": str(decision.get("severity") or "").lower(),
                    "reasons": soft_reasons,
                }
            )

    return {
        "ok": not failures,
        "verified": "live_review_recall_funnel",
        "run_id": run_id,
        "gold_count": len(gold_findings),
        "matched_gold_count": matched_gold_count,
        "recall": matched_gold_count / len(gold_findings) if gold_findings else 0.0,
        "final_finding_count": len(final_findings),
        "candidate_decision_count": len(decisions),
        "fallback_event_count": len(fallback_sizes),
        "fallback_max_units": fallback_max_units,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify recall safety from one live Worker review run.")
    parser.add_argument("--report", required=True, help="JSON report with run_id, gold_findings, final_findings, events and candidate_decisions")
    parser.add_argument("--line-tolerance", type=int, default=5)
    parser.add_argument("--out", help="Optional output JSON path")
    args = parser.parse_args()

    report = json.loads(Path(args.report).read_text("utf-8"))
    result = evaluate_live_review_recall(report, line_tolerance=args.line_tolerance)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
