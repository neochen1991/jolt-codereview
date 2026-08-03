from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "mr-backend" / "worker"
sys.path.insert(0, str(WORKER))

from orchestration.nodes.judge_findings import (  # noqa: E402
    calibrate_findings_with_change_intent,
    dedupe_same_line_same_issue_findings,
    judge_candidate_findings,
)
from orchestration.nodes.verify_findings import verify_candidate_findings  # noqa: E402


PUBLISHABLE_SEVERITIES = {"critical", "high", "medium", "low"}


def score_labeled_cases(cases: list[dict[str, Any]], duplicate_groups: list[list[str]] | None = None) -> dict[str, Any]:
    true_positive = sum(1 for item in cases if item["expected"] and item["published"])
    false_positive = sum(1 for item in cases if not item["expected"] and item["published"])
    false_negative = sum(1 for item in cases if item["expected"] and not item["published"])
    true_negative = sum(1 for item in cases if not item["expected"] and not item["published"])
    expected_high = [item for item in cases if item["expected"] and item.get("severity") in {"critical", "high"}]
    recalled_high = [item for item in expected_high if item["published"]]
    false_positives = [item for item in cases if not item["expected"] and item["published"]]
    groups = duplicate_groups or []
    return {
        "case_count": len(cases),
        "tp": true_positive,
        "fp": false_positive,
        "fn": false_negative,
        "tn": true_negative,
        "precision": round(true_positive / (true_positive + false_positive), 4) if true_positive + false_positive else 1.0,
        "recall": round(true_positive / (true_positive + false_negative), 4) if true_positive + false_negative else 1.0,
        "high_severity_recall": round(len(recalled_high) / len(expected_high), 4) if expected_high else 1.0,
        "false_positives_by_intent": dict(sorted(Counter(str(item["intent"]) for item in false_positives).items())),
        "false_positives_by_category": dict(sorted(Counter(str(item["category"]) for item in false_positives).items())),
        "duplicate_group_count": len(groups),
        "duplicate_rate": round(sum(max(0, len(group) - 1) for group in groups) / max(1, len(cases)), 4),
    }


def _finding(**overrides: Any) -> dict[str, Any]:
    item = {
        "agent_id": "coding_agent",
        "severity": "medium",
        "confidence": 0.92,
        "dedupe_hash": "fixture",
        "file_path": "src/main/java/com/acme/RefundService.java",
        "line_start": 20,
        "line_end": 20,
        "title": "异常处理缺陷",
        "problem_description": "失败被吞掉。",
        "evidence": "catch (Exception e)",
        "recommendation": "保留失败传播。",
        "suggested_code": "throw new RefundFailedException(e);",
        "covered_rules": ["CODE-EXC-003"],
    }
    item.update(overrides)
    return item


def _verify(finding: dict[str, Any], source: str) -> bool:
    accepted, _rejected = verify_candidate_findings(
        [finding],
        {str(finding["file_path"])},
        {str(finding["agent_id"]): {"min_confidence": 0.75}},
        set(),
        {str(finding["file_path"]): [(1, 200)]},
        {str(rule) for rule in finding.get("covered_rules") or []},
        lambda _file, _line, window=5: source,
    )
    return bool(accepted)


def _is_published(items: list[dict[str, Any]]) -> bool:
    return any(
        str(item.get("severity") or "").lower() in PUBLISHABLE_SEVERITIES and int(item.get("selected", 1) or 0) == 1
        for item in items
    )


def run_quality_fixture() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []

    rethrow = _finding(
        title="异常被吞掉后继续执行",
        problem_description="catch Exception 没有把失败传播给调用方。",
    )
    cases.append({
        "case_id": "safe-rethrow",
        "expected": False,
        "published": _verify(rethrow, 'try { refund(); } catch (Exception e) { throw new RefundFailedException("failed", e); }'),
        "severity": "medium",
        "intent": "behavior_change",
        "category": "SWALLOWED_EXCEPTION",
    })

    guarded_null = _finding(
        title="request 可能为空导致空指针",
        problem_description="request 未判空就被解引用。",
        evidence="request.getId()",
        covered_rules=["CODE-NULL-001"],
    )
    cases.append({
        "case_id": "guarded-null",
        "expected": False,
        "published": _verify(guarded_null, "if (request == null) { return; } repository.load(request.getId());"),
        "severity": "medium",
        "intent": "behavior_change",
        "category": "NULL_SAFETY",
    })

    true_swallow = _finding(
        title="查询异常被吞掉并返回空集合",
        problem_description="查询失败被伪装成没有数据。",
        evidence="catch (Exception e) { logger.warn(\"load failed\", e); return Collections.emptyList(); }",
    )
    cases.append({
        "case_id": "true-swallow",
        "expected": True,
        "published": _verify(true_swallow, 'try { return load(); } catch (Exception e) { logger.warn("load failed", e); return Collections.emptyList(); }'),
        "severity": "medium",
        "intent": "behavior_change",
        "category": "SWALLOWED_EXCEPTION_READ",
    })

    safe_old_issue = _finding(context_unit_id="safe-unit", causal_delta="unchanged", covered_rules=[], rule_id="")
    safe_kept, _ = calibrate_findings_with_change_intent(
        [safe_old_issue],
        [{"unit_id": "safe-unit", "change_intent": {"labels": ["logging_only"], "semantic_delta": "behavior_preserving"}}],
    )
    cases.append({
        "case_id": "logging-only-old-issue",
        "expected": False,
        "published": _is_published(safe_kept),
        "severity": "medium",
        "intent": "logging_only",
        "category": "BROAD_EXCEPTION",
    })

    mixed_defect = _finding(
        agent_id="security_agent",
        severity="high",
        context_unit_id="mixed-unit",
        causal_delta="introduced",
        title="SQL 拼接存在注入风险",
        problem_description="请求参数被拼接进 SQL。",
        evidence='statement.executeQuery("select * from refund where id=" + request.getId())',
        covered_rules=["SEC-INJECT-003"],
    )
    mixed_kept, _ = calibrate_findings_with_change_intent(
        [mixed_defect],
        [{"unit_id": "mixed-unit", "change_intent": {"labels": ["mixed"], "semantic_delta": "unknown"}}],
    )
    cases.append({
        "case_id": "mixed-sql-injection",
        "expected": True,
        "published": _is_published(mixed_kept),
        "severity": "high",
        "intent": "mixed",
        "category": "SQL_INJECTION",
    })

    bound = _finding(
        severity="high",
        context_unit_id="bound-unit",
        causal_delta="unchanged",
        bound_rule_id="TEAM-AUTH-001",
        review_batch_label="bound_rule:TEAM-AUTH-001",
        covered_rules=["TEAM-AUTH-001"],
    )
    bound_kept, _ = calibrate_findings_with_change_intent(
        [bound],
        [{"unit_id": "bound-unit", "change_intent": {"labels": ["rename_or_move"], "semantic_delta": "behavior_preserving"}}],
    )
    cases.append({
        "case_id": "bound-rule-safe-intent",
        "expected": True,
        "published": _is_published(bound_kept),
        "severity": "high",
        "intent": "rename_or_move",
        "category": "BOUND_RULE",
    })

    naming = [
        _finding(
            dedupe_hash=f"naming-{line}",
            severity="medium",
            line_start=line,
            line_end=line,
            title=title,
            problem_description="变量命名不符合 lowerCamelCase。",
            evidence=evidence,
            covered_rules=["ALI-NAMING-001"],
            rule_id="ALI-NAMING-001",
        )
        for line, title, evidence in [
            (12, "Refund_ID 不符合命名规范", "String Refund_ID = id;"),
            (84, "Merchant_CODE 未采用驼峰命名", "String Merchant_CODE = code;"),
        ]
    ]
    naming_selected, _ = judge_candidate_findings(naming, [], max_findings=20)
    naming_merged, naming_rejected = dedupe_same_line_same_issue_findings(naming_selected)
    naming_published = _is_published(naming_merged)
    cases.append({
        "case_id": "style-advisory-aggregate",
        "expected": False,
        "published": naming_published,
        "severity": "info",
        "intent": "behavior_change",
        "category": "JAVA_NAMING",
    })

    report = score_labeled_cases(cases, duplicate_groups=[])
    report["aggregated_duplicate_count"] = len(naming_rejected)
    report["post_aggregation_finding_count"] = len(naming_merged)
    report["cases"] = cases
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-precision", type=float, default=1.0)
    parser.add_argument("--min-recall", type=float, default=1.0)
    parser.add_argument("--min-high-severity-recall", type=float, default=1.0)
    parser.add_argument("--max-duplicate-rate", type=float, default=0.0)
    args = parser.parse_args()
    report = run_quality_fixture()
    failures: list[str] = []
    for key, minimum in [
        ("precision", args.min_precision),
        ("recall", args.min_recall),
        ("high_severity_recall", args.min_high_severity_recall),
    ]:
        if float(report[key]) < minimum:
            failures.append(f"{key} {report[key]} < {minimum}")
    if float(report["duplicate_rate"]) > args.max_duplicate_rate:
        failures.append(f"duplicate_rate {report['duplicate_rate']} > {args.max_duplicate_rate}")
    if int(report.get("aggregated_duplicate_count") or 0) < 1:
        failures.append("same-file advisory duplicate was not aggregated")
    report["ok"] = not failures
    report["failures"] = failures
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
