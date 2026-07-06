from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def finding_id(finding: dict[str, Any]) -> str:
    return str(finding.get("finding_id") or finding.get("id") or finding.get("dedupe_hash") or "<unknown>")


def quality_trace(finding: dict[str, Any]) -> dict[str, Any]:
    value = finding.get("quality_trace")
    return value if isinstance(value, dict) else {}


def evidence_score(finding: dict[str, Any]) -> dict[str, Any]:
    direct = finding.get("evidence_score")
    if isinstance(direct, dict):
        return direct
    trace_score = quality_trace(finding).get("evidence_score")
    return trace_score if isinstance(trace_score, dict) else {}


def consensus_agents(finding: dict[str, Any]) -> list[Any]:
    direct = finding.get("consensus_agents")
    if isinstance(direct, list):
        return direct
    trace_agents = quality_trace(finding).get("consensus_agents")
    return trace_agents if isinstance(trace_agents, list) else []


def critic_verdict(finding: dict[str, Any]) -> dict[str, Any]:
    verdict = quality_trace(finding).get("critic_verdict")
    return verdict if isinstance(verdict, dict) else {}


def validate_quality_fields(findings: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for finding in findings:
        fid = finding_id(finding)
        score = evidence_score(finding)
        if not score:
            failures.append(f"{fid}: missing evidence_score")
        else:
            try:
                value = float(score.get("score"))
            except (TypeError, ValueError):
                failures.append(f"{fid}: evidence_score.score is not numeric")
            else:
                if value < 0 or value > 1:
                    failures.append(f"{fid}: evidence_score.score {value} outside [0, 1]")
            components = score.get("components")
            if not isinstance(components, dict) or not components:
                failures.append(f"{fid}: missing evidence_score.components")
        if not consensus_agents(finding):
            failures.append(f"{fid}: missing consensus_agents")
        verdict = critic_verdict(finding)
        if not verdict:
            failures.append(f"{fid}: missing quality_trace.critic_verdict")
        elif not str(verdict.get("verdict") or "").strip():
            failures.append(f"{fid}: critic_verdict.verdict is empty")
    return failures


def run_score(args: argparse.Namespace, report_path: Path) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/score_real_pr_reviews.py",
        "--gold",
        args.gold,
        "--findings",
        args.findings,
        "--out",
        str(report_path),
        "--min-precision",
        str(args.min_precision),
        "--min-recall",
        str(args.min_recall),
        "--max-negative-fp",
        str(args.max_negative_fp),
    ]
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        raise SystemExit(result.returncode)
    return json.loads(report_path.read_text("utf-8"))


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def report_threshold_failures(report: dict[str, Any], args: argparse.Namespace) -> list[str]:
    failures: list[str] = []
    high_accuracy = _float(report.get("high_severity_accuracy") or report.get("high_recall"))
    if high_accuracy < args.min_high_severity_accuracy:
        failures.append(f"high_severity_accuracy {high_accuracy} < {args.min_high_severity_accuracy}")
    if int(report.get("mr_count") or 0) < args.min_mrs:
        failures.append(f"mr_count {report.get('mr_count')} < {args.min_mrs}")
    if int(report.get("gold_count") or 0) < args.min_gold:
        failures.append(f"gold_count {report.get('gold_count')} < {args.min_gold}")
    if int(report.get("negative_mr_count") or 0) < args.min_negative_mrs:
        failures.append(f"negative_mr_count {report.get('negative_mr_count')} < {args.min_negative_mrs}")
    quality_summary = report.get("quality_summary") if isinstance(report.get("quality_summary"), dict) else {}
    weak_findings = quality_summary.get("weak_findings") if isinstance(quality_summary.get("weak_findings"), list) else []
    if len(weak_findings) > args.max_weak_evidence:
        failures.append(f"weak_evidence_count {len(weak_findings)} > {args.max_weak_evidence}")
    action_items = report.get("action_items") if isinstance(report.get("action_items"), list) else []
    if len(action_items) > args.max_action_items:
        failures.append(f"action_item_count {len(action_items)} > {args.max_action_items}")

    for rule_id, row in sorted((report.get("by_rule") or {}).items()):
        if not isinstance(row, dict):
            continue
        if int(row.get("gold_count") or 0) <= 0 and int(row.get("finding_count") or 0) <= 0:
            continue
        precision = _float(row.get("precision"))
        recall = _float(row.get("recall"))
        if precision < args.min_rule_precision:
            failures.append(f"rule {rule_id} precision {precision} < {args.min_rule_precision}")
        if recall < args.min_rule_recall:
            failures.append(f"rule {rule_id} recall {recall} < {args.min_rule_recall}")

    for mr_id, row in sorted((report.get("by_mr") or {}).items()):
        if not isinstance(row, dict) or bool(row.get("is_negative")):
            continue
        if int(row.get("gold_count") or 0) <= 0:
            continue
        precision = _float(row.get("precision"))
        recall = _float(row.get("recall"))
        if precision < args.min_mr_precision:
            failures.append(f"mr {mr_id} precision {precision} < {args.min_mr_precision}")
        if recall < args.min_mr_recall:
            failures.append(f"mr {mr_id} recall {recall} < {args.min_mr_recall}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", default="evaluation/real_gold_set.jsonl")
    parser.add_argument("--findings", default="evaluation/real_findings.jsonl")
    parser.add_argument("--min-precision", type=float, default=0.80)
    parser.add_argument("--min-recall", type=float, default=0.65)
    parser.add_argument("--min-high-severity-accuracy", type=float, default=0.80)
    parser.add_argument("--max-negative-fp", type=int, default=0)
    parser.add_argument("--min-mrs", type=int, default=1)
    parser.add_argument("--min-gold", type=int, default=10)
    parser.add_argument("--min-negative-mrs", type=int, default=0)
    parser.add_argument("--max-weak-evidence", type=int, default=0)
    parser.add_argument("--max-action-items", type=int, default=0)
    parser.add_argument("--min-rule-precision", type=float, default=0.80)
    parser.add_argument("--min-rule-recall", type=float, default=0.65)
    parser.add_argument("--min-mr-precision", type=float, default=0.80)
    parser.add_argument("--min-mr-recall", type=float, default=0.65)
    args = parser.parse_args()

    findings = read_jsonl(ROOT / args.findings)
    with tempfile.TemporaryDirectory(prefix="jolt-real-pr-quality-") as tmpdir:
        report_path = Path(tmpdir) / "real-pr-report.json"
        report = run_score(args, report_path)

    failures = validate_quality_fields(findings)
    failures.extend(report_threshold_failures(report, args))
    high_accuracy = _float(report.get("high_severity_accuracy") or report.get("high_recall"))
    quality_summary = report.get("quality_summary") if isinstance(report.get("quality_summary"), dict) else {}
    weak_findings = quality_summary.get("weak_findings") if isinstance(quality_summary.get("weak_findings"), list) else []
    action_items = report.get("action_items") if isinstance(report.get("action_items"), list) else []
    if failures:
        raise SystemExit("real PR quality gate failed: " + "; ".join(failures))

    print(
        json.dumps(
            {
                "ok": True,
                "verified": "real_pr_quality",
                "precision": report.get("precision"),
                "recall": report.get("recall"),
                "high_severity_accuracy": high_accuracy,
                "finding_count": report.get("finding_count"),
                "mr_count": report.get("mr_count"),
                "gold_count": report.get("gold_count"),
                "negative_false_positive_count": report.get("negative_false_positive_count"),
                "weak_evidence_count": len(weak_findings),
                "action_item_count": len(action_items),
                "quality_fields_checked": len(findings),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
