from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def rule_ids(item: dict[str, Any]) -> set[str]:
    values = [
        item.get("rule_id"),
        item.get("tool_rule_id"),
        item.get("normalized_rule_category"),
        *item.get("covered_rules", []),
    ]
    return {str(value) for value in values if value}


def evidence_text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(key) or "") for key in ["evidence", "title", "problem_description", "recommendation"]).lower()


def matches(gold: dict[str, Any], finding: dict[str, Any], line_tolerance: int) -> bool:
    gold_file = str(gold.get("file") or gold.get("file_path") or "")
    finding_file = str(finding.get("file_path") or finding.get("file") or "")
    if gold_file != finding_file:
        return False
    gold_line = int(gold.get("line") or gold.get("line_start") or 0)
    finding_line = int(finding.get("line_start") or finding.get("line") or 0)
    if gold_line and finding_line and abs(gold_line - finding_line) > line_tolerance:
        return False
    expected_rule = str(gold.get("rule_id") or "")
    if expected_rule and expected_rule not in rule_ids(finding):
        return False
    keywords = [str(item).lower() for item in gold.get("evidence_keywords", []) if str(item).strip()]
    text = evidence_text(finding)
    return not keywords or any(keyword in text for keyword in keywords)


def evaluate(gold_items: list[dict[str, Any]], findings: list[dict[str, Any]], line_tolerance: int = 5) -> dict[str, Any]:
    findings_by_mr: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        findings_by_mr[str(finding.get("mr_id") or finding.get("merge_request_id") or "")].append(finding)
    matched_finding_ids: set[int] = set()
    matched_gold: list[str] = []
    missed_gold: list[dict[str, Any]] = []
    by_rule: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fn": 0})
    for gold in gold_items:
        candidates = findings_by_mr.get(str(gold.get("mr_id") or ""), [])
        match_index = next((index for index, finding in enumerate(candidates) if matches(gold, finding, line_tolerance)), None)
        rule = str(gold.get("rule_id") or "unknown")
        if match_index is None:
            missed_gold.append(gold)
            by_rule[rule]["fn"] += 1
            continue
        matched_finding_ids.add(id(candidates[match_index]))
        matched_gold.append(str(gold.get("id") or ""))
        by_rule[rule]["tp"] += 1
    false_positives = [finding for finding in findings if id(finding) not in matched_finding_ids]
    tp = len(matched_gold)
    fn = len(missed_gold)
    fp = len(false_positives)
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    high_items = [item for item in gold_items if str(item.get("severity")) == "high"]
    high_matched = len([item for item in high_items if str(item.get("id") or "") in set(matched_gold)])
    high_recall = high_matched / max(1, len(high_items))
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "high_recall": round(high_recall, 4),
        "gold_count": len(gold_items),
        "finding_count": len(findings),
        "missed_gold_ids": [str(item.get("id")) for item in missed_gold],
        "false_positive_count": fp,
        "by_rule": by_rule,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", default="evaluation/gold_set.jsonl")
    parser.add_argument("--findings", default="evaluation/sample_findings.jsonl")
    parser.add_argument("--out", default="evaluation/report.json")
    parser.add_argument("--line-tolerance", type=int, default=5)
    args = parser.parse_args()
    report = evaluate(read_jsonl(Path(args.gold)), read_jsonl(Path(args.findings)), args.line_tolerance)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
