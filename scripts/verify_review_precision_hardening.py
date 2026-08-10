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
from orchestration.quality.final_consolidation import merge_consolidation_groups  # noqa: E402
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


def _consolidation_quality_report() -> dict[str, Any]:
    findings = [
        _finding(
            "idem-a",
            line=11,
            title="退款接口缺少幂等保护",
            description="重复请求没有使用退款请求号去重，可能造成重复退款。",
            evidence="refund(command)",
            rule="BE-IDEMPOTENCY-001",
            agent="backend_agent",
        ),
        _finding(
            "idem-b",
            line=11,
            title="重复退款请求未防护",
            description="相同 refundRequestId 可以再次执行退款。",
            evidence="gateway.refund(command)",
            rule="SEC-RISK-006",
            agent="security_agent",
        ),
        _finding(
            "auth-a",
            line=18,
            title="更新入口缺少权限校验",
            description="执行更新前没有验证操作人权限。",
            evidence="repository.update(request)",
            rule="SEC-AUTH-001",
            agent="security_agent",
        ),
        _finding(
            "auth-b",
            line=22,
            title="服务调用可以绕过授权检查",
            description="同一更新调用链没有 authorization guard。",
            evidence="service.update(request)",
            rule="BE-API-001",
            agent="backend_agent",
        ),
        _finding(
            "sql-injection",
            line=30,
            title="SQL 字符串拼接存在注入风险",
            description="请求参数直接拼接到 SQL。",
            evidence='query("select * from t where id=" + request.id)',
            rule="SEC-INJECT-003",
            agent="security_agent",
        ),
        _finding(
            "unbounded-query",
            line=30,
            title="查询缺少分页或结果上限",
            description="查询没有 LIMIT，可能返回全部记录。",
            evidence="query(request)",
            rule="PERF-QUERY-001",
            agent="performance_agent",
        ),
        _finding(
            "null-production",
            line=40,
            title="返回值缺少 null 保护",
            description="生产代码直接解引用可能为空的返回值。",
            evidence="repository.find(id).getName()",
            rule="CODE-NULL-001",
            agent="coding_agent",
        ),
        {
            **_finding(
                "missing-test",
                line=55,
                title="缺少空返回值回归测试",
                description="测试没有覆盖 repository 返回 null 的场景。",
                evidence="test only covers existing entity",
                rule="TEST-COVER-001",
                agent="test_agent",
            ),
            "file_path": "src/ReviewServiceTest.java",
        },
    ]
    same_line_groups = [{"idem-a", "idem-b"}]
    nearby_groups = [{"auth-a", "auth-b"}]
    forbidden_pairs = [{"sql-injection", "unbounded-query"}, {"null-production", "missing-test"}]
    proposed_groups = [
        {"member_ids": ["f_01", "f_02"], "reason": "same idempotency root cause"},
        {"member_ids": ["f_03", "f_04"], "reason": "same missing authorization root cause"},
    ]
    request_id_to_hash = {f"f_{index:02d}": str(item["dedupe_hash"]) for index, item in enumerate(findings, start=1)}
    proposed_hash_groups = [
        {request_id_to_hash[member] for member in group["member_ids"]}
        for group in proposed_groups
    ]
    merged, _ = merge_consolidation_groups(findings, proposed_groups, model_metadata={"model": "quality-gate-fixture"})

    def merge_rate(expected: list[set[str]]) -> float:
        if not expected:
            return 1.0
        merged_count = sum(1 for group in expected if any(group <= proposed for proposed in proposed_hash_groups))
        return round(merged_count / len(expected), 4)

    false_merge_count = sum(1 for pair in forbidden_pairs if any(pair <= proposed for proposed in proposed_hash_groups))
    expected_groups = [*same_line_groups, *nearby_groups]
    duplicate_members_before = sum(len(group) - 1 for group in expected_groups)
    duplicate_members_after = sum(
        len(group) - 1
        for group in expected_groups
        if not any(group <= proposed for proposed in proposed_hash_groups)
    )
    return {
        "consolidation_input_finding_count": len(findings),
        "consolidation_output_finding_count": len(merged),
        "same_line_paraphrase_merge_rate": merge_rate(same_line_groups),
        "nearby_root_cause_merge_rate": merge_rate(nearby_groups),
        "false_merge_count": false_merge_count,
        "false_merge_rate": round(false_merge_count / max(1, len(forbidden_pairs)), 4),
        "consolidation_duplicate_rate_before": round(duplicate_members_before / max(1, len(findings)), 4),
        "consolidation_duplicate_rate_after": round(duplicate_members_after / max(1, len(merged)), 4),
        "consolidation_output_count_invariant": len(merged) <= len(findings),
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
        **_consolidation_quality_report(),
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
    same_line_rate = report.get("same_line_paraphrase_merge_rate")
    if same_line_rate is not None and float(same_line_rate) < 1.0:
        failures.append(f"same_line_paraphrase_merge_rate {same_line_rate} < 1.0")
    nearby_rate = report.get("nearby_root_cause_merge_rate")
    if nearby_rate is not None and float(nearby_rate) < 0.9:
        failures.append(f"nearby_root_cause_merge_rate {nearby_rate} < 0.9")
    false_merge_rate = report.get("false_merge_rate")
    if false_merge_rate is not None and float(false_merge_rate) >= 0.02:
        failures.append(f"false_merge_rate {false_merge_rate} >= 0.02")
    consolidation_duplicate_rate = report.get("consolidation_duplicate_rate_after")
    if consolidation_duplicate_rate is not None and float(consolidation_duplicate_rate) >= 0.03:
        failures.append(f"consolidation_duplicate_rate_after {consolidation_duplicate_rate} >= 0.03")
    if report.get("consolidation_output_count_invariant") is False:
        failures.append("consolidation_output_count_invariant is false")
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
