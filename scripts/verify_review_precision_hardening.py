from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "mr-backend" / "worker"
sys.path.insert(0, str(WORKER))

from orchestration.nodes.judge_findings import filter_to_diff_introduced_findings  # noqa: E402
from orchestration.quality.issue_identity import cluster_canonical_issues  # noqa: E402
from verify_intent_aware_precision import derive_duplicate_groups, score_scope_violations  # noqa: E402


@dataclass
class ChangedFile:
    filename: str
    patch: str
    status: str = "modified"


PATCH = """@@ -10,1 +10,2 @@
 old();
+repository.update(request);
@@ -24,1 +25,2 @@
 oldQuery();
+query(request);
"""


def _finding(finding_id: str, *, line: int, title: str, description: str, evidence: str, rule: str, agent: str) -> dict[str, Any]:
    return {
        "finding_id": finding_id,
        "agent_id": agent,
        "severity": "high" if agent == "security_agent" else "medium",
        "confidence": 0.91,
        "dedupe_hash": finding_id,
        "file_path": "src/ReviewService.java",
        "line_start": line,
        "line_end": line,
        "title": title,
        "problem_description": description,
        "evidence": evidence,
        "recommendation": "修复该问题。",
        "covered_rules": [rule],
        "selected": 1,
    }


def build_hardening_report() -> dict[str, Any]:
    files = [ChangedFile("src/ReviewService.java", PATCH)]
    raw = [
        _finding(
            "auth-a",
            line=11,
            title="缺少权限验证",
            description="更新前未验证当前用户权限。",
            evidence="repository.update(request)",
            rule="SEC-AUTH-001",
            agent="security_agent",
        ),
        _finding(
            "auth-b",
            line=11,
            title="接口没有鉴权保护",
            description="调用更新方法前没有授权判断。",
            evidence="repository.update(request)",
            rule="BE-API-001",
            agent="backend_agent",
        ),
        _finding(
            "sql",
            line=26,
            title="SQL 字符串拼接存在注入风险",
            description="请求参数被直接拼接到 SQL。",
            evidence='String sql = "select * from t where id=" + request.getId(); query(sql);',
            rule="SEC-INJECT-003",
            agent="security_agent",
        ),
        _finding(
            "limit",
            line=26,
            title="查询缺少分页或结果上限",
            description="该查询可能返回全部数据。",
            evidence="query(request)",
            rule="PERF-QUERY-001",
            agent="performance_agent",
        ),
    ]
    raw_duplicate_groups = derive_duplicate_groups(raw)
    canonical, duplicate_rejections = cluster_canonical_issues(raw)
    scope_input = [
        *canonical,
        _finding(
            "context-line",
            line=25,
            title="旧代码问题",
            description="问题只存在于上下文行。",
            evidence="oldQuery()",
            rule="CODE-GENERAL-001",
            agent="coding_agent",
        ),
        {
            **_finding(
                "unchanged-file",
                line=11,
                title="非变更文件问题",
                description="该文件不属于当前变更。",
                evidence="update()",
                rule="CODE-GENERAL-001",
                agent="coding_agent",
            ),
            "file_path": "src/Unchanged.java",
        },
    ]
    final_findings, scope_rejections = filter_to_diff_introduced_findings(scope_input, files)
    final_duplicate_groups = derive_duplicate_groups(final_findings)
    return {
        "raw_finding_count": len(raw),
        "raw_duplicate_group_count": len(raw_duplicate_groups),
        "canonical_finding_count": len(final_findings),
        "canonical_duplicate_rejection_count": len(duplicate_rejections),
        "scope_rejection_count": len(scope_rejections),
        "scope_rejection_reasons": sorted(
            {reason for item in scope_rejections for reason in (item.get("rejected_reasons") or [])}
        ),
        "final_duplicate_group_count": len(final_duplicate_groups),
        "final_duplicate_rate": round(
            sum(len(group) - 1 for group in final_duplicate_groups) / max(1, len(final_findings)), 4
        ),
        **score_scope_violations(final_findings, files),
    }


def quality_gate_failures(report: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if float(report.get("final_duplicate_rate") or 0) > 0:
        failures.append(f"final_duplicate_rate {report['final_duplicate_rate']} > 0")
    for key in ("off_diff_published_count", "unchanged_file_published_count", "automatic_relocation_count"):
        value = int(report.get(key) or 0)
        if value > 0:
            failures.append(f"{key} {value} > 0")
    return failures


def main() -> int:
    report = build_hardening_report()
    failures = quality_gate_failures(report)
    report["ok"] = not failures
    report["failures"] = failures
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
