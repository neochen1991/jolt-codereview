from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from score_real_pr_reviews import evaluate, read_jsonl


ROOT = Path(__file__).resolve().parents[1]


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_false_positives(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "finding_id": str(item.get("finding_id") or ""),
                "mr_id": str(item.get("mr_id") or ""),
                "file_path": str(item.get("file_path") or ""),
                "line_start": item.get("line_start"),
                "covered_rules": sorted(str(rule) for rule in item.get("covered_rules") or []),
                "evidence_score": item.get("evidence_score"),
            }
            for item in items
        ],
        key=lambda item: stable_json(item),
    )


def normalize_rule_rows(rows: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, row in rows.items():
        normalized[str(key)] = {
            "tp": row.get("tp"),
            "fp": row.get("fp"),
            "fn": row.get("fn"),
            "gold_count": row.get("gold_count"),
            "finding_count": row.get("finding_count"),
            "precision": row.get("precision"),
            "recall": row.get("recall"),
            "missed_gold_ids": sorted(str(item) for item in row.get("missed_gold_ids") or []),
        }
    return dict(sorted(normalized.items()))


def normalize_mr_rows(rows: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, row in rows.items():
        normalized[str(key)] = {
            "tp": row.get("tp"),
            "fp": row.get("fp"),
            "fn": row.get("fn"),
            "gold_count": row.get("gold_count"),
            "finding_count": row.get("finding_count"),
            "precision": row.get("precision"),
            "recall": row.get("recall"),
            "is_negative": bool(row.get("is_negative")),
            "missed_gold_ids": sorted(str(item) for item in row.get("missed_gold_ids") or []),
            "false_positive_finding_ids": sorted(str(item) for item in row.get("false_positive_finding_ids") or []),
        }
    return dict(sorted(normalized.items()))


def quality_fingerprint(report: dict[str, Any]) -> dict[str, Any]:
    quality = report.get("quality_summary") if isinstance(report.get("quality_summary"), dict) else {}
    evidence = quality.get("evidence_score") if isinstance(quality.get("evidence_score"), dict) else {}
    return {
        "tp": report.get("tp"),
        "fp": report.get("fp"),
        "fn": report.get("fn"),
        "precision": report.get("precision"),
        "recall": report.get("recall"),
        "high_severity_accuracy": report.get("high_severity_accuracy") or report.get("high_recall"),
        "gold_count": report.get("gold_count"),
        "mr_count": report.get("mr_count"),
        "finding_count": report.get("finding_count"),
        "negative_false_positive_count": report.get("negative_false_positive_count"),
        "missed_gold_ids": sorted(str(item) for item in report.get("missed_gold_ids") or []),
        "false_positive_findings": normalize_false_positives(report.get("false_positive_findings") or []),
        "by_rule": normalize_rule_rows(report.get("by_rule") or {}),
        "by_mr": normalize_mr_rows(report.get("by_mr") or {}),
        "quality_summary": {
            "evidence_score": {
                "count": evidence.get("count"),
                "min": evidence.get("min"),
                "avg": evidence.get("avg"),
                "max": evidence.get("max"),
                "below_0_35": evidence.get("below_0_35"),
                "below_0_50": evidence.get("below_0_50"),
            },
            "missing_evidence_score_count": quality.get("missing_evidence_score_count"),
            "missing_consensus_agents_count": quality.get("missing_consensus_agents_count"),
            "missing_critic_verdict_count": quality.get("missing_critic_verdict_count"),
        },
    }


def assert_same(label: str, expected: dict[str, Any], actual: dict[str, Any]) -> None:
    if expected == actual:
        return
    raise SystemExit(
        "real PR repeatability gate failed for "
        + label
        + "\nexpected="
        + json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True)
        + "\nactual="
        + json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", default="evaluation/real_gold_set.jsonl")
    parser.add_argument("--findings", default="evaluation/real_findings.jsonl")
    parser.add_argument("--line-tolerance", type=int, default=5)
    args = parser.parse_args()

    gold = read_jsonl(ROOT / args.gold)
    findings = read_jsonl(ROOT / args.findings)
    baseline = quality_fingerprint(evaluate(gold, findings, args.line_tolerance))
    repeated = quality_fingerprint(evaluate(gold, findings, args.line_tolerance))
    reversed_input = quality_fingerprint(evaluate(list(reversed(gold)), list(reversed(findings)), args.line_tolerance))

    assert_same("repeat_same_input", baseline, repeated)
    assert_same("reversed_input_order", baseline, reversed_input)
    print(
        json.dumps(
            {
                "ok": True,
                "verified": "real_pr_scorer_determinism",
                "tp": baseline["tp"],
                "fp": baseline["fp"],
                "fn": baseline["fn"],
                "precision": baseline["precision"],
                "recall": baseline["recall"],
                "mr_count": baseline["mr_count"],
                "gold_count": baseline["gold_count"],
                "finding_count": baseline["finding_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
