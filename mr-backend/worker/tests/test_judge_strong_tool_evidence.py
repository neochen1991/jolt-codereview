from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

from orchestration.nodes.judge_findings import (
    _fill_missing_tool_coverage,
    _is_low_precision_unbacked_advisory,
    _prune_low_signal_final_findings,
    judge_candidate_findings,
)


def finding(rule_id: str, title: str, *, file_path: str, line: int, confidence: float = 0.9) -> dict:
    return {
        "severity": "high" if rule_id.startswith("SEC-") else "medium",
        "confidence": confidence,
        "agent_id": "security_agent" if rule_id.startswith("SEC-") else "performance_agent",
        "head_sha": "sha",
        "dedupe_hash": f"hash-{rule_id}",
        "file_path": file_path,
        "line_start": line,
        "line_end": line,
        "title": title,
        "problem_description": title,
        "recommendation": "fix it",
        "suggested_code": "fixed();",
        "evidence": f"Evidence: {title}",
        "covered_rules": [rule_id],
        "tool_name": "java_web_static",
        "source_type": "tool",
        "source_tool_observation": {
            "tool_name": "java_web_static",
            "rule_id": rule_id,
            "confidence": confidence,
            "file_path": file_path,
            "line_start": line,
            "message": title,
        },
        "verification_flags": ["tool_promoted"],
    }


def test_strong_tool_findings_keep_distinct_root_causes_on_same_line() -> None:
    final, rejected = judge_candidate_findings(
        [
            finding(
                "SEC-INJECT-003",
                "SQL 注入漏洞 - 用户输入直接拼接入 SQL 字符串",
                file_path="src/main/java/com/acme/payment/service/PaymentQueryService.java",
                line=22,
                confidence=0.95,
            ),
            finding(
                "PERF-QUERY-001",
                "查询缺少分页或结果上限",
                file_path="src/main/java/com/acme/payment/service/PaymentQueryService.java",
                line=22,
                confidence=0.9,
            ),
        ],
        [],
        max_findings=10,
    )
    rules = {rule for item in final for rule in item.get("covered_rules", [])}
    assert {"SEC-INJECT-003", "PERF-QUERY-001"}.issubset(rules), (final, rejected)


def test_strong_ddd_tool_finding_is_not_pruned_as_weak_advisory() -> None:
    final, rejected = judge_candidate_findings(
        [
            finding(
                "DDD-VO-002",
                "领域模型使用弱类型 Map 表达业务属性",
                file_path="src/main/java/com/acme/payment/domain/PaymentAggregate.java",
                line=12,
                confidence=0.91,
            )
        ],
        [],
        max_findings=10,
    )
    rules = {rule for item in final for rule in item.get("covered_rules", [])}
    assert "DDD-VO-002" in rules, (final, rejected)


def test_strong_tool_finding_with_secondary_ddd_rule_is_not_pruned() -> None:
    kept, rejected = _prune_low_signal_final_findings(
        [
            {
                **finding(
                    "SEC-INJECT-003",
                    "SQL 拼接业务入参，违反参数绑定规范",
                    file_path="src/main/java/com/acme/payment/service/PaymentQueryService.java",
                    line=22,
                    confidence=0.95,
                ),
                "covered_rules": ["SEC-INJECT-003", "DDD-CTX-005"],
                "tool_rule_id": "SEC-INJECT-003",
                "judge_adjustment": "debate_keep",
            }
        ]
    )
    rules = {rule for item in kept for rule in item.get("covered_rules", [])}
    assert "SEC-INJECT-003" in rules, (kept, rejected)


def test_soft_audit_state_claim_without_exact_tool_support_is_dropped() -> None:
    item = {
        "severity": "medium",
        "confidence": 0.85,
        "agent_id": "coding_agent",
        "file_path": "src/main/java/com/acme/payment/api/PaymentAdminController.java",
        "line_start": 35,
        "title": "AuditRequest 记录缺少审计时间和原因字段",
        "problem_description": "AuditRequest 缺少审计时间和原因字段。",
        "evidence": "record AuditRequest(String paymentId, String operator) {}",
        "covered_rules": ["CODE-STATE-004"],
        "tool_rule_id": "CODE-STATE-004",
    }
    assert _is_low_precision_unbacked_advisory(item, [])


def test_missing_tool_coverage_fills_rule_when_existing_finding_is_multi_rule_bundle() -> None:
    selected = [
        {
            "severity": "high",
            "confidence": 0.93,
            "agent_id": "coding_agent",
            "file_path": "src/main/java/com/acme/payment/api/PaymentAdminController.java",
            "line_start": 23,
            "line_end": 23,
            "title": "POST 副作用接口缺少幂等保护",
            "problem_description": "新增 POST 接口缺少幂等保护，合并证据里包含 String.valueOf(payload.get(\"userId\"))。",
            "evidence": "String userId = String.valueOf(payload.get(\"userId\"));",
            "recommendation": "使用 DTO + Bean Validation，或对 Map 字段做显式 required/type 校验后再进入业务逻辑。",
            "covered_rules": ["CODE-NULL-001", "BE-API-001", "BE-IDEMP-004"],
            "verification_flags": ["tool_promoted"],
        }
    ]
    observations = [
        {
            "tool_name": "java_web_static",
            "rule_id": "CODE-NULL-001",
            "severity": "medium",
            "confidence": 0.86,
            "file_path": "src/main/java/com/acme/payment/api/PaymentAdminController.java",
            "line_start": 23,
            "line_end": 23,
            "message": "Map payload field is converted with String.valueOf; missing fields become literal \"null\".\nEvidence: String userId = String.valueOf(payload.get(\"userId\"));",
        }
    ]

    filled = _fill_missing_tool_coverage(selected, observations, max_findings=5)

    code_null_findings = [item for item in filled if item.get("covered_rules") == ["CODE-NULL-001"]]
    assert len(code_null_findings) == 1, filled
    assert "String.valueOf" in code_null_findings[0]["evidence"], code_null_findings


def test_missing_tool_coverage_uses_registry_promotable_rules_beyond_legacy_fill_list() -> None:
    observations = [
        {
            "tool_name": "java_web_static",
            "rule_id": "CODE-RESOURCE-005",
            "severity": "medium",
            "confidence": 0.91,
            "file_path": "src/main/java/com/acme/export/ExportService.java",
            "line_start": 42,
            "line_end": 42,
            "message": "Connection autoCommit is changed without restoring it before returning the pooled connection.",
        }
    ]

    filled = _fill_missing_tool_coverage([], observations, max_findings=5)

    assert any(item.get("covered_rules") == ["CODE-RESOURCE-005"] for item in filled), filled


def test_missing_tool_coverage_requires_high_confidence_and_precise_line() -> None:
    observations = [
        {
            "tool_name": "java_web_static",
            "rule_id": "CODE-RESOURCE-005",
            "severity": "medium",
            "confidence": 0.84,
            "file_path": "src/main/java/com/acme/export/ExportService.java",
            "line_start": 42,
            "message": "Connection autoCommit is changed without restoring it.",
        },
        {
            "tool_name": "java_web_static",
            "rule_id": "SEC-DEBUG-011",
            "severity": "high",
            "confidence": 0.95,
            "file_path": "src/main/java/com/acme/debug/DebugController.java",
            "message": "Debug endpoint is exposed.",
        },
    ]

    filled = _fill_missing_tool_coverage([], observations, max_findings=5)

    assert filled == [], filled


if __name__ == "__main__":
    test_strong_tool_findings_keep_distinct_root_causes_on_same_line()
    test_strong_ddd_tool_finding_is_not_pruned_as_weak_advisory()
    test_strong_tool_finding_with_secondary_ddd_rule_is_not_pruned()
    test_soft_audit_state_claim_without_exact_tool_support_is_dropped()
    test_missing_tool_coverage_fills_rule_when_existing_finding_is_multi_rule_bundle()
    test_missing_tool_coverage_uses_registry_promotable_rules_beyond_legacy_fill_list()
    test_missing_tool_coverage_requires_high_confidence_and_precise_line()
