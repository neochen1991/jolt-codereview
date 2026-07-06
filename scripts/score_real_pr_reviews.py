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


def finding_id(finding: dict[str, Any]) -> str:
    return norm(finding.get("finding_id") or finding.get("id") or finding.get("dedupe_hash")) or "<unknown>"


def gold_id(gold: dict[str, Any]) -> str:
    return norm(gold.get("id")) or "|".join(
        [
            norm(gold.get("mr_id")),
            norm(gold.get("file") or gold.get("file_path")),
            norm(gold.get("line") or gold.get("line_start")),
            norm(gold.get("rule_id")),
        ]
    )


def line_number(item: dict[str, Any]) -> int:
    try:
        return int(item.get("line_start") or item.get("line") or 0)
    except (TypeError, ValueError):
        return 0


def gold_sort_key(gold: dict[str, Any]) -> tuple[str, str, int, str, str]:
    return (
        norm(gold.get("mr_id")),
        norm(gold.get("file") or gold.get("file_path")),
        line_number(gold),
        norm(gold.get("rule_id")),
        gold_id(gold),
    )


def finding_sort_key(finding: dict[str, Any]) -> tuple[str, str, int, str]:
    return (
        norm(finding.get("mr_id") or finding.get("merge_request_id")),
        norm(finding.get("file_path") or finding.get("file")),
        line_number(finding),
        finding_id(finding),
    )


def line_distance(gold: dict[str, Any], finding: dict[str, Any]) -> int:
    gold_line = line_number(gold)
    finding_line = line_number(finding)
    if not gold_line or not finding_line:
        return 0
    return abs(gold_line - finding_line)


def quality_trace(finding: dict[str, Any]) -> dict[str, Any]:
    value = finding.get("quality_trace")
    return value if isinstance(value, dict) else {}


def evidence_score(finding: dict[str, Any]) -> dict[str, Any]:
    direct = finding.get("evidence_score")
    if isinstance(direct, dict):
        return direct
    trace_score = quality_trace(finding).get("evidence_score")
    return trace_score if isinstance(trace_score, dict) else {}


def evidence_score_value(finding: dict[str, Any]) -> float | None:
    score = evidence_score(finding).get("score")
    try:
        return float(score)
    except (TypeError, ValueError):
        return None


def consensus_agents(finding: dict[str, Any]) -> list[Any]:
    direct = finding.get("consensus_agents")
    if isinstance(direct, list):
        return direct
    trace_agents = quality_trace(finding).get("consensus_agents")
    return trace_agents if isinstance(trace_agents, list) else []


def critic_verdict(finding: dict[str, Any]) -> dict[str, Any]:
    verdict = quality_trace(finding).get("critic_verdict")
    return verdict if isinstance(verdict, dict) else {}


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
    positive_gold = sorted(
        [item for item in gold_items if norm(item.get("ground_truth") or "true_positive") != "negative"],
        key=gold_sort_key,
    )
    positive_mr_ids = {norm(item.get("mr_id")) for item in positive_gold if norm(item.get("mr_id"))}
    findings_by_mr: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in sorted(findings, key=finding_sort_key):
        findings_by_mr[norm(finding.get("mr_id") or finding.get("merge_request_id"))].append(finding)

    matched_finding_ids: set[int] = set()
    matched_gold_ids: set[str] = set()
    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    missed: list[dict[str, Any]] = []
    for gold in positive_gold:
        candidates = findings_by_mr.get(norm(gold.get("mr_id")), [])
        candidate_matches = [
            (line_distance(gold, finding), finding_sort_key(finding), index)
            for index, finding in enumerate(candidates)
            if id(finding) not in matched_finding_ids and matches(gold, finding, tolerance)
        ]
        match_index = sorted(candidate_matches)[0][2] if candidate_matches else None
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
        "by_mr": by_mr_report(positive_gold, matched_pairs, missed, false_positives, negative_mr_ids),
        "quality_summary": quality_summary(findings),
        "action_items": action_items(positive_gold, matched_pairs, missed, false_positives, findings),
        "missed_gold_ids": [norm(item.get("id")) for item in missed],
        "false_positive_findings": [
            {
                "finding_id": finding_id(finding),
                "mr_id": finding.get("mr_id"),
                "file_path": finding.get("file_path"),
                "line_start": finding.get("line_start"),
                "title": finding.get("title"),
                "covered_rules": finding.get("covered_rules") or [],
                "evidence_score": evidence_score_value(finding),
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


def by_mr_report(
    positive_gold: list[dict[str, Any]],
    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    missed: list[dict[str, Any]],
    false_positives: list[dict[str, Any]],
    negative_mr_ids: set[str],
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
            "is_negative": False,
            "missed_gold_ids": [],
            "false_positive_finding_ids": [],
        }
    )
    for mr_id in negative_mr_ids:
        rows[mr_id]["is_negative"] = True
    for gold in positive_gold:
        mr_id = norm(gold.get("mr_id")) or "unclassified"
        rows[mr_id]["gold_count"] += 1
    for gold, _finding in matched_pairs:
        mr_id = norm(gold.get("mr_id")) or "unclassified"
        rows[mr_id]["tp"] += 1
        rows[mr_id]["finding_count"] += 1
    for gold in missed:
        mr_id = norm(gold.get("mr_id")) or "unclassified"
        rows[mr_id]["fn"] += 1
        rows[mr_id]["missed_gold_ids"].append(norm(gold.get("id")))
    for finding in false_positives:
        mr_id = norm(finding.get("mr_id") or finding.get("merge_request_id")) or "unclassified"
        rows[mr_id]["fp"] += 1
        rows[mr_id]["finding_count"] += 1
        rows[mr_id]["false_positive_finding_ids"].append(finding_id(finding))
    for row in rows.values():
        row["precision"] = round(row["tp"] / max(1, row["tp"] + row["fp"]), 4)
        row["recall"] = round(row["tp"] / max(1, row["tp"] + row["fn"]), 4)
        row["missed_gold_ids"] = [item for item in row["missed_gold_ids"] if item]
    return dict(sorted(rows.items()))


def quality_summary(findings: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [score for finding in findings if (score := evidence_score_value(finding)) is not None]
    weak_findings: list[dict[str, Any]] = []
    missing_evidence = 0
    missing_consensus = 0
    missing_critic = 0
    for finding in findings:
        missing: list[str] = []
        score = evidence_score_value(finding)
        if score is None:
            missing_evidence += 1
            missing.append("evidence_score")
        if not consensus_agents(finding):
            missing_consensus += 1
            missing.append("consensus_agents")
        if not critic_verdict(finding):
            missing_critic += 1
            missing.append("critic_verdict")
        if missing or (score is not None and score < 0.5):
            weak_findings.append({
                "finding_id": finding_id(finding),
                "mr_id": finding.get("mr_id") or finding.get("merge_request_id"),
                "file_path": finding.get("file_path"),
                "line_start": finding.get("line_start"),
                "title": finding.get("title"),
                "covered_rules": sorted(rule_ids(finding)),
                "evidence_score": score,
                "missing_quality_fields": missing,
            })
    return {
        "finding_count": len(findings),
        "evidence_score": {
            "count": len(scores),
            "min": round(min(scores), 4) if scores else None,
            "avg": round(sum(scores) / len(scores), 4) if scores else None,
            "max": round(max(scores), 4) if scores else None,
            "below_0_35": len([score for score in scores if score < 0.35]),
            "below_0_50": len([score for score in scores if score < 0.5]),
        },
        "missing_evidence_score_count": missing_evidence,
        "missing_consensus_agents_count": missing_consensus,
        "missing_critic_verdict_count": missing_critic,
        "weak_findings": sorted(
            weak_findings,
            key=lambda item: (item["evidence_score"] is None, item["evidence_score"] or 0, norm(item["finding_id"])),
        ),
    }


def action_items(
    positive_gold: list[dict[str, Any]],
    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    missed: list[dict[str, Any]],
    false_positives: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rule_report = by_rule_report(positive_gold, matched_pairs, missed, false_positives)
    items: list[dict[str, Any]] = []
    for rule, row in rule_report.items():
        if row["fn"]:
            items.append({
                "type": "recall_gap",
                "rule_id": rule,
                "priority": row["fn"],
                "message": f"{rule} missed {row['fn']} gold finding(s)",
                "missed_gold_ids": row["missed_gold_ids"],
            })
        if row["fp"]:
            items.append({
                "type": "precision_gap",
                "rule_id": rule,
                "priority": row["fp"],
                "message": f"{rule} produced {row['fp']} unmatched finding(s)",
            })
    weak = quality_summary(findings)["weak_findings"]
    for finding in weak[:10]:
        items.append({
            "type": "weak_evidence",
            "finding_id": finding["finding_id"],
            "priority": 1,
            "message": "finding has weak or incomplete quality evidence",
            "evidence_score": finding["evidence_score"],
            "missing_quality_fields": finding["missing_quality_fields"],
        })
    return sorted(items, key=lambda item: (-int(item.get("priority") or 0), norm(item.get("type")), norm(item.get("rule_id") or item.get("finding_id"))))


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
