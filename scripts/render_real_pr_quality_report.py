from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from score_real_pr_reviews import evaluate, read_jsonl


def fmt_number(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(fmt_number(value) for value in row) + " |")
    return lines


def top_rule_rows(report: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for rule, item in report.get("by_rule", {}).items():
        if int(item.get("fn") or 0) or int(item.get("fp") or 0) or float(item.get("recall") or 0) < 1:
            rows.append([
                rule,
                item.get("tp", 0),
                item.get("fp", 0),
                item.get("fn", 0),
                item.get("precision", 0),
                item.get("recall", 0),
                ", ".join(item.get("missed_gold_ids") or []),
            ])
    return sorted(rows, key=lambda row: (-int(row[3]), -int(row[2]), str(row[0])))


def top_mr_rows(report: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for mr_id, item in report.get("by_mr", {}).items():
        if int(item.get("fn") or 0) or int(item.get("fp") or 0) or bool(item.get("is_negative")):
            rows.append([
                mr_id,
                "yes" if item.get("is_negative") else "no",
                item.get("tp", 0),
                item.get("fp", 0),
                item.get("fn", 0),
                item.get("precision", 0),
                item.get("recall", 0),
                ", ".join(item.get("missed_gold_ids") or item.get("false_positive_finding_ids") or []),
            ])
    return sorted(rows, key=lambda row: (row[1] != "yes", -int(row[4]), -int(row[3]), str(row[0])))


def weak_evidence_rows(report: dict[str, Any], limit: int) -> list[list[Any]]:
    rows = []
    for item in (report.get("quality_summary", {}).get("weak_findings") or [])[:limit]:
        rows.append([
            item.get("finding_id", ""),
            item.get("mr_id", ""),
            item.get("file_path", ""),
            item.get("line_start", ""),
            item.get("evidence_score"),
            ", ".join(item.get("covered_rules") or []),
            ", ".join(item.get("missing_quality_fields") or []),
        ])
    return rows


def action_item_rows(report: dict[str, Any], limit: int) -> list[list[Any]]:
    rows = []
    for item in (report.get("action_items") or [])[:limit]:
        rows.append([
            item.get("type", ""),
            item.get("rule_id") or item.get("finding_id") or "",
            item.get("priority", ""),
            item.get("message", ""),
        ])
    return rows


def render(report: dict[str, Any], *, title: str, weak_limit: int = 10, action_limit: int = 20) -> str:
    quality = report.get("quality_summary") or {}
    evidence = quality.get("evidence_score") or {}
    lines: list[str] = [
        f"# {title}",
        "",
        "## Summary",
        "",
        *table(
            ["metric", "value"],
            [
                ["precision", report.get("precision")],
                ["recall", report.get("recall")],
                ["high_severity_accuracy", report.get("high_severity_accuracy") or report.get("high_recall")],
                ["gold_count", report.get("gold_count")],
                ["finding_count", report.get("finding_count")],
                ["mr_count", report.get("mr_count")],
                ["negative_mr_count", report.get("negative_mr_count")],
                ["negative_false_positive_count", report.get("negative_false_positive_count")],
            ],
        ),
        "",
        "## Evidence Quality",
        "",
        *table(
            ["metric", "value"],
            [
                ["evidence_score_min", evidence.get("min")],
                ["evidence_score_avg", evidence.get("avg")],
                ["evidence_score_max", evidence.get("max")],
                ["evidence_score_below_0_35", evidence.get("below_0_35")],
                ["evidence_score_below_0_50", evidence.get("below_0_50")],
                ["missing_evidence_score_count", quality.get("missing_evidence_score_count")],
                ["missing_consensus_agents_count", quality.get("missing_consensus_agents_count")],
                ["missing_critic_verdict_count", quality.get("missing_critic_verdict_count")],
            ],
        ),
        "",
    ]

    action_rows = action_item_rows(report, action_limit)
    lines.extend(["## Action Items", ""])
    if action_rows:
        lines.extend(table(["type", "target", "priority", "message"], action_rows))
    else:
        lines.append("No action items.")
    lines.append("")

    rule_rows = top_rule_rows(report)
    lines.extend(["## Rule Gaps", ""])
    if rule_rows:
        lines.extend(table(["rule", "tp", "fp", "fn", "precision", "recall", "missed_gold_ids"], rule_rows))
    else:
        lines.append("No rule-level recall or precision gaps.")
    lines.append("")

    mr_rows = top_mr_rows(report)
    lines.extend(["## MR Gaps", ""])
    if mr_rows:
        lines.extend(table(["mr_id", "negative", "tp", "fp", "fn", "precision", "recall", "ids"], mr_rows))
    else:
        lines.append("No MR-level recall or precision gaps.")
    lines.append("")

    weak_rows = weak_evidence_rows(report, weak_limit)
    lines.extend(["## Weak Evidence Findings", ""])
    if weak_rows:
        lines.extend(table(["finding_id", "mr_id", "file", "line", "score", "rules", "missing_fields"], weak_rows))
    else:
        lines.append("No weak evidence findings.")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", default="evaluation/real_gold_set.jsonl")
    parser.add_argument("--findings", default="evaluation/real_findings.jsonl")
    parser.add_argument("--out", default="docs/reports/real-pr-quality-report.md")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--line-tolerance", type=int, default=5)
    parser.add_argument("--title", default="Real PR Review Quality Report")
    args = parser.parse_args()

    report = evaluate(read_jsonl(Path(args.gold)), read_jsonl(Path(args.findings)), args.line_tolerance)
    markdown = render(report, title=args.title)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, "utf-8")
    if args.json_out:
        json_path = Path(args.json_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({"ok": True, "report": str(out_path), "precision": report.get("precision"), "recall": report.get("recall")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
