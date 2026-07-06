from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def norm(value: Any) -> str:
    return str(value or "").strip()


def rule_ids(finding: dict[str, Any]) -> set[str]:
    values = [finding.get("rule_id"), finding.get("tool_rule_id"), finding.get("normalized_rule_category")]
    values.extend(finding.get("covered_rules") or [])
    return {norm(value) for value in values if norm(value)}


def finding_text(finding: dict[str, Any]) -> str:
    return " ".join(
        norm(finding.get(key))
        for key in ["title", "problem_description", "evidence", "recommendation"]
    ).lower()


def matches(gold: dict[str, Any], finding: dict[str, Any], tolerance: int) -> bool:
    if norm(gold.get("mr_id")) != norm(finding.get("mr_id") or finding.get("merge_request_id")):
        return False
    gold_file = norm(gold.get("file") or gold.get("file_path"))
    finding_file = norm(finding.get("file_path") or finding.get("file"))
    if gold_file and finding_file != gold_file:
        return False
    gold_line = int(gold.get("line") or gold.get("line_start") or 0)
    finding_line = int(finding.get("line_start") or finding.get("line") or 0)
    if gold_line and finding_line and abs(gold_line - finding_line) > tolerance:
        return False
    expected_rule = norm(gold.get("rule_id"))
    if expected_rule and expected_rule not in rule_ids(finding):
        return False
    keywords = [norm(item).lower() for item in gold.get("evidence_keywords", []) if norm(item)]
    text = finding_text(finding)
    return not keywords or any(keyword in text for keyword in keywords)


def evaluate(gold_items: list[dict[str, Any]], findings: list[dict[str, Any]], tolerance: int) -> dict[str, Any]:
    positive_gold = [item for item in gold_items if norm(item.get("ground_truth") or "true_positive") != "negative"]
    positive_mr_ids = {norm(item.get("mr_id")) for item in positive_gold if norm(item.get("mr_id"))}
    findings_by_mr: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        findings_by_mr[norm(finding.get("mr_id") or finding.get("merge_request_id"))].append(finding)

    matched_finding_ids: set[int] = set()
    matched_gold_ids: set[str] = set()
    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    missed: list[dict[str, Any]] = []
    for gold in positive_gold:
        candidates = findings_by_mr.get(norm(gold.get("mr_id")), [])
        match_index = next(
            (
                index
                for index, finding in enumerate(candidates)
                if id(finding) not in matched_finding_ids and matches(gold, finding, tolerance)
            ),
            None,
        )
        if match_index is None:
            missed.append(gold)
            continue
        matched_finding = candidates[match_index]
        matched_finding_ids.add(id(matched_finding))
        matched_gold_ids.add(norm(gold.get("id")))
        matched_pairs.append((gold, matched_finding))

    false_positives = [finding for finding in findings if id(finding) not in matched_finding_ids]
    negative_mr_ids = {
        norm(item.get("mr_id"))
        for item in gold_items
        if norm(item.get("ground_truth")) == "negative" and norm(item.get("mr_id"))
    }
    negative_false_positives = [finding for finding in findings if norm(finding.get("mr_id")) in negative_mr_ids]
    tp = len(matched_gold_ids)
    fp = len(false_positives)
    fn = len(missed)
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    high_gold = [item for item in positive_gold if norm(item.get("severity")).lower() in {"critical", "high"}]
    high_matched = [item for item in high_gold if norm(item.get("id")) in matched_gold_ids]
    high_severity_accuracy = round(len(high_matched) / max(1, len(high_gold)), 4)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "high_recall": high_severity_accuracy,
        "high_severity_accuracy": high_severity_accuracy,
        "gold_count": len(positive_gold),
        "mr_count": len(positive_mr_ids | negative_mr_ids),
        "positive_mr_count": len(positive_mr_ids),
        "finding_count": len(findings),
        "negative_mr_count": len(negative_mr_ids),
        "negative_false_positive_count": len(negative_false_positives),
        "by_rule": by_rule_report(positive_gold, matched_pairs, missed, false_positives),
        "missed_gold_ids": [norm(item.get("id")) for item in missed],
        "false_positive_findings": [
            {
                "mr_id": finding.get("mr_id"),
                "file_path": finding.get("file_path"),
                "line_start": finding.get("line_start"),
                "title": finding.get("title"),
                "covered_rules": finding.get("covered_rules") or [],
            }
            for finding in false_positives
        ],
    }


def by_rule_report(
    positive_gold: list[dict[str, Any]],
    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    missed: list[dict[str, Any]],
    false_positives: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "tp": 0,
            "fp": 0,
            "fn": 0,
            "gold_count": 0,
            "finding_count": 0,
            "precision": 0.0,
            "recall": 0.0,
            "missed_gold_ids": [],
        }
    )
    for gold in positive_gold:
        rule = norm(gold.get("rule_id")) or "unclassified"
        rows[rule]["gold_count"] += 1
    for gold, _finding in matched_pairs:
        rule = norm(gold.get("rule_id")) or "unclassified"
        rows[rule]["tp"] += 1
    for gold in missed:
        rule = norm(gold.get("rule_id")) or "unclassified"
        rows[rule]["fn"] += 1
        rows[rule]["missed_gold_ids"].append(norm(gold.get("id")))
    for finding in false_positives:
        rules = sorted(rule_ids(finding)) or ["unclassified"]
        for rule in rules:
            rows[rule]["fp"] += 1
            rows[rule]["finding_count"] += 1
    for gold, _finding in matched_pairs:
        rule = norm(gold.get("rule_id")) or "unclassified"
        rows[rule]["finding_count"] += 1
    for rule, row in rows.items():
        row["precision"] = round(row["tp"] / max(1, row["tp"] + row["fp"]), 4)
        row["recall"] = round(row["tp"] / max(1, row["tp"] + row["fn"]), 4)
        row["missed_gold_ids"] = [item for item in row["missed_gold_ids"] if item]
    return dict(sorted(rows.items()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", default="evaluation/real_gold_set.jsonl")
    parser.add_argument("--findings", default="evaluation/real_findings.jsonl")
    parser.add_argument("--out", default="evaluation/real_report.json")
    parser.add_argument("--line-tolerance", type=int, default=5)
    parser.add_argument("--min-precision", type=float, default=0.70)
    parser.add_argument("--min-recall", type=float, default=0.60)
    parser.add_argument("--max-negative-fp", type=int, default=0)
    args = parser.parse_args()
    report = evaluate(read_jsonl(Path(args.gold)), read_jsonl(Path(args.findings)), args.line_tolerance)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["precision"] < args.min_precision:
        raise SystemExit(f"precision below target: {report['precision']} < {args.min_precision}")
    if report["recall"] < args.min_recall:
        raise SystemExit(f"recall below target: {report['recall']} < {args.min_recall}")
    if report["negative_false_positive_count"] > args.max_negative_fp:
        raise SystemExit("negative false positives exceed target")


if __name__ == "__main__":
    main()
