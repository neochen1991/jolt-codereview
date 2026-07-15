from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

from orchestration.judging.evidence_score import apply_evidence_score_policy
from orchestration.nodes.judge_findings import (
    _critic_rejected,
    _merge_finding_metadata,
    _prune_low_signal_final_findings,
    build_quality_trace,
    dedupe_same_line_same_issue_findings,
    judge_candidate_findings,
    reconcile_rules_with_tool_observations,
    retain_as_needs_review,
    should_retain_final_candidate_for_review,
    should_retain_low_precision_without_tool_support,
)


def agent_finding(**overrides: object) -> dict:
    item = {
        "severity": "medium",
        "confidence": 0.78,
        "agent_id": "security_agent",
        "dedupe_hash": "agent-only-1",
        "file_path": "src/main/java/com/acme/payment/api/AdminController.java",
        "line_start": 42,
        "line_end": 42,
        "title": "管理接口缺少权限校验",
        "problem_description": "新增管理接口可以修改支付状态，但没有权限校验。",
        "evidence": "@PostMapping(\"/admin/payments/{id}/force\")",
        "recommendation": "为该接口增加服务端权限校验，并补充未授权访问测试。",
        "suggested_code": "@PreAuthorize(\"hasAuthority('PAYMENT_ADMIN')\")",
        "covered_rules": ["SEC-AUTHZ-002"],
        "verification_flags": ["low_evidence_match"],
    }
    item.update(overrides)
    return item


def test_agent_only_complete_finding_is_retained_without_tool_support() -> None:
    finding = agent_finding()

    assert should_retain_low_precision_without_tool_support(finding, []) is True


def test_minimax_source_grounded_unattributed_finding_is_retained_for_review() -> None:
    finding = agent_finding(
        severity="high",
        confidence=0.72,
        covered_rules=[],
        rule_id="",
        tool_rule_id="",
        verification_flags=["rule_attribution_missing"],
        title="异常被吞掉后返回空列表",
        problem_description="查询失败被伪装成没有数据。",
        evidence="catch (Exception e) { e.printStackTrace(); return Collections.emptyList(); }",
        recommendation="记录结构化错误并向上返回明确失败，避免把异常等同于空结果。",
    )

    assert should_retain_low_precision_without_tool_support(finding, []) is True
    assert should_retain_final_candidate_for_review(
        finding,
        reason="evidence_contract_not_satisfied",
        source_observations=[],
    ) is True


def test_unattributed_claim_without_location_or_source_evidence_is_rejectable() -> None:
    finding = agent_finding(
        severity="high",
        covered_rules=[],
        rule_id="",
        tool_rule_id="",
        file_path="",
        line_start=0,
        line_end=0,
        evidence="",
        verification_flags=["rule_attribution_missing"],
    )

    assert should_retain_low_precision_without_tool_support(finding, []) is False
    assert should_retain_final_candidate_for_review(
        finding,
        reason="evidence_contract_not_satisfied",
        source_observations=[],
    ) is False


def test_title_like_rule_does_not_retain_advisory_without_rule_anchor() -> None:
    finding = agent_finding(
        severity="info",
        confidence=0.75,
        title="DirectFieldAccessor 强制类型转换安全性确认",
        rule_id="DirectFieldAccessor 强制类型转换安全性确认",
        tool_rule_id="DirectFieldAccessor 强制类型转换安全性确认",
        covered_rules=[],
        verification_flags=["low_evidence_match", "source_location_supported"],
    )

    assert should_retain_low_precision_without_tool_support(finding, []) is False
    assert should_retain_final_candidate_for_review(
        finding,
        reason="evidence_contract_not_satisfied",
        source_observations=[],
    ) is False


def test_custom_rule_id_can_still_retain_needs_review_without_tool_support() -> None:
    finding = agent_finding(
        rule_id="PAYMENT-AUTH-001",
        covered_rules=["PAYMENT-AUTH-001"],
    )

    assert should_retain_low_precision_without_tool_support(finding, []) is True


def test_minor_agent_only_candidate_is_not_retained_without_tool_or_bound_rule() -> None:
    finding = agent_finding(
        severity="minor",
        confidence=0.82,
        rule_id="CODE-STATE-004",
        covered_rules=["CODE-STATE-004"],
        title="接口返回类型与实际使用方法的类型不匹配导致强制类型转换",
    )

    assert should_retain_final_candidate_for_review(
        finding,
        reason="not_selected_final_issue",
        source_observations=[],
    ) is False


def test_partial_evidence_contract_is_retained_as_needs_review() -> None:
    finding = agent_finding(suggested_code="")
    trace = build_quality_trace(finding, [])

    retained = retain_as_needs_review(
        finding,
        reason="evidence_contract_not_satisfied",
        quality_trace=trace,
        source_observations=[],
        tool_provenance=[],
    )

    assert retained["selected"] == 0
    assert retained["judge_adjustment"] == "needs_review:evidence_contract_not_satisfied"
    assert retained["quality_trace"]["judge"]["review_tier"] == "needs_review"
    assert retained["quality_trace"]["evidence_contract"]["decision_hint"] in {"advisory_candidate", "needs_review"}


def test_quality_trace_preserves_bound_evidence_contract() -> None:
    bound_contract = {
        "version": "bound_evidence_contract_v1",
        "rule_id": "SEC-CMD-001",
        "checkpoint_id": "SEC-CMD-001",
        "status": "partial",
        "missing_required_evidence": ["外部输入来源"],
    }
    trace = build_quality_trace(agent_finding(bound_evidence_contract=bound_contract), [])

    assert trace["bound_evidence_contract"] == bound_contract


def test_skill_checkpoint_rule_is_not_reconciled_to_tool_rule() -> None:
    finding = agent_finding(
        covered_rules=["SEC-CMD-001"],
        rule_id="SEC-CMD-001",
        skill_key="secure-review-skill",
        checkpoint_id="SEC-CMD-001",
        title="命令注入检查",
        source_observations=[
            {
                "tool_name": "java_web_static",
                "rule_id": "SEC-INJECT-003",
                "file_path": "src/main/java/com/acme/payment/api/AdminController.java",
                "line_start": 42,
                "message": "Runtime.exec receives request parameter",
            }
        ],
    )

    reconciled = reconcile_rules_with_tool_observations(finding, finding["source_observations"])

    assert reconciled["covered_rules"] == ["SEC-CMD-001"], reconciled
    assert reconciled["rule_id"] == "SEC-CMD-001", reconciled
    assert "rule_reconciliation" not in reconciled, reconciled


def test_bound_skill_merge_does_not_add_lower_priority_tool_rule() -> None:
    primary = agent_finding(
        covered_rules=["SEC-CMD-001"],
        rule_id="SEC-CMD-001",
        skill_key="secure-review-skill",
        checkpoint_id="SEC-CMD-001",
        review_batch_label="bound_skill:secure-review-skill:SEC-CMD-001",
    )
    secondary = agent_finding(
        agent_id="security_agent",
        covered_rules=["SEC-INJECT-003"],
        rule_id="SEC-INJECT-003",
        tool_rule_id="SEC-INJECT-003",
        verification_flags=["tool_promoted"],
    )

    merged = _merge_finding_metadata(primary, secondary)

    assert merged["covered_rules"] == ["SEC-CMD-001"], merged
    assert merged["rule_id"] == "SEC-CMD-001", merged
    assert "SEC-INJECT-003" not in merged["covered_rules"], merged
    assert set(merged["merged_agent_ids"]) == {"security_agent"}, merged


def test_bound_skill_merge_uses_batch_label_when_checkpoint_field_missing() -> None:
    primary = agent_finding(
        covered_rules=["SEC-CMD-001", "SEC-INJECT-003"],
        rule_id="SEC-CMD-001",
        skill_key="secure-review-skill",
        review_batch_label="bound_skill:secure-review-skill:SEC-CMD-001",
    )
    secondary = agent_finding(
        covered_rules=["SEC-INJECT-003"],
        rule_id="SEC-INJECT-003",
        tool_rule_id="SEC-INJECT-003",
        verification_flags=["tool_promoted"],
    )

    merged = _merge_finding_metadata(primary, secondary)

    assert merged["covered_rules"] == ["SEC-CMD-001"], merged
    assert merged["rule_id"] == "SEC-CMD-001", merged
    assert "SEC-INJECT-003" not in merged["covered_rules"], merged


def test_bound_skill_merge_recovers_retry_label_with_colon_checkpoint() -> None:
    primary = agent_finding(
        covered_rules=["SKILL:secure-review-skill", "SEC-INJECT-003"],
        rule_id="SKILL:secure-review-skill",
        skill_key="secure-review-skill",
        review_batch_label="bound_skill:secure-review-skill:SKILL:secure-review-skill:coverage_retry",
    )
    secondary = agent_finding(
        covered_rules=["SEC-INJECT-003"],
        rule_id="SEC-INJECT-003",
        tool_rule_id="SEC-INJECT-003",
        verification_flags=["tool_promoted"],
    )

    merged = _merge_finding_metadata(primary, secondary)

    assert merged["covered_rules"] == ["SKILL:secure-review-skill"], merged
    assert "coverage_retry" not in merged["covered_rules"], merged
    assert "SEC-INJECT-003" not in merged["covered_rules"], merged


def test_bound_skill_merge_restores_authoritative_id_when_current_rules_are_dirty() -> None:
    primary = agent_finding(
        covered_rules=["SEC-INJECT-003"],
        rule_id="SEC-INJECT-003",
        skill_key="secure-review-skill",
        review_batch_label="bound_skill:secure-review-skill:SEC-CMD-001",
    )
    secondary = agent_finding(
        covered_rules=["SEC-INJECT-003"],
        rule_id="SEC-INJECT-003",
        tool_rule_id="SEC-INJECT-003",
        verification_flags=["tool_promoted"],
    )

    merged = _merge_finding_metadata(primary, secondary)

    assert merged["covered_rules"] == ["SEC-CMD-001"], merged
    assert merged["rule_id"] == "SEC-CMD-001", merged
    assert "SEC-INJECT-003" not in merged["covered_rules"], merged


def test_bound_skill_merge_does_not_add_lower_priority_skipped_rule() -> None:
    primary = agent_finding(
        covered_rules=["SEC-CMD-001"],
        skipped_rules=["SEC-CMD-001"],
        rule_id="SEC-CMD-001",
        skill_key="secure-review-skill",
        review_batch_label="bound_skill:secure-review-skill:SEC-CMD-001",
    )
    secondary = agent_finding(
        covered_rules=["SEC-INJECT-003"],
        skipped_rules=["SEC-INJECT-003"],
        rule_id="SEC-INJECT-003",
        tool_rule_id="SEC-INJECT-003",
        verification_flags=["tool_promoted"],
    )

    merged = _merge_finding_metadata(primary, secondary)

    assert merged["skipped_rules"] == ["SEC-CMD-001"], merged
    assert "SEC-INJECT-003" not in merged["skipped_rules"], merged


def test_business_semantic_dedupe_merges_cross_layer_audit_findings() -> None:
    service = agent_finding(
        agent_id="refund_risk_skill_agent",
        covered_rules=["BIZ-AUDIT-001"],
        rule_id="BIZ-AUDIT-001",
        file_path="src/main/java/com/acme/refund/service/RefundService.java",
        line_start=22,
        line_end=22,
        title="批量审核服务方法缺少审计记录",
        problem_description="approveBatch 使用 operator 执行批量退款审核，但没有写入审计记录。",
        evidence="approveBatch 方法循环处理退款单；operator/reason 参与审核，未调用 RefundAuditRecord。",
        review_batch_label="bound_skill:refund-risk-review-skill:BIZ-AUDIT-001",
    )
    controller = agent_finding(
        agent_id="refund_risk_skill_agent",
        covered_rules=["BIZ-AUDIT-001"],
        rule_id="BIZ-AUDIT-001",
        file_path="src/main/java/com/acme/refund/api/RefundAdminController.java",
        line_start=16,
        line_end=16,
        title="批量审核接口缺少审计记录",
        problem_description="admin batch approve 接口接收 operator/reason，但没有审计写入。",
        evidence="@PostMapping(\"/admin/refunds/batch-approve\") 接收 operator 和 reason，未写入审计。",
        review_batch_label="bound_skill:refund-risk-review-skill:BIZ-AUDIT-001",
    )

    merged, rejected = dedupe_same_line_same_issue_findings([controller, service])

    assert len(merged) == 1, merged
    assert len(rejected) == 1, rejected
    assert rejected[0]["rejected_reasons"] == ["deduped_same_business_issue"], rejected
    assert merged[0]["file_path"] == "src/main/java/com/acme/refund/service/RefundService.java", merged
    semantic = merged[0]["quality_trace"]["semantic_dedupe"]
    assert semantic["merged_count"] == 2, semantic
    assert semantic["signature"].startswith("BIZ-AUDIT-001|"), semantic
    assert semantic["related_locations"][0]["file_path"] == "src/main/java/com/acme/refund/api/RefundAdminController.java", semantic
    assert "RefundAdminController.java:16" in merged[0]["evidence"], merged


def test_same_root_cause_on_different_lines_is_not_deduped_lower_rank() -> None:
    merchant_query = agent_finding(
        dedupe_hash="sql-merchant-query",
        covered_rules=["SEC-SQL-001"],
        rule_id="SEC-SQL-001",
        normalized_rule_category="SQL_INJECTION",
        file_path="src/main/java/com/acme/refund/repository/RefundRepository.java",
        line_start=28,
        line_end=28,
        title="商户退款查询 SQL 拼接存在注入风险",
        problem_description="merchantId 直接拼接进 pending refund 查询 SQL。",
        evidence="where merchant_id = '" + " + merchantId + " + "' and status = 'PENDING'",
        recommendation="使用 PreparedStatement 绑定 merchantId。",
    )
    status_query = agent_finding(
        dedupe_hash="sql-status-query",
        covered_rules=["SEC-SQL-001"],
        rule_id="SEC-SQL-001",
        normalized_rule_category="SQL_INJECTION",
        file_path="src/main/java/com/acme/refund/repository/RefundRepository.java",
        line_start=96,
        line_end=96,
        title="状态统计 SQL 拼接存在注入风险",
        problem_description="status 直接拼接进 count refund 查询 SQL。",
        evidence="where status = '" + " + status + " + "' group by merchant_id",
        recommendation="使用 PreparedStatement 绑定 status。",
    )

    final, rejected = judge_candidate_findings([merchant_query, status_query], [], max_findings=5)

    assert {(item["title"], item["line_start"]) for item in final} == {
        ("商户退款查询 SQL 拼接存在注入风险", 28),
        ("状态统计 SQL 拼接存在注入风险", 96),
    }, (final, rejected)
    assert not any("deduped_lower_rank" in (item.get("rejected_reasons") or []) for item in rejected), rejected


def test_unselected_structured_candidate_is_retained_for_review() -> None:
    finding = agent_finding(confidence=0.62, selected=0)

    assert should_retain_final_candidate_for_review(finding, reason="not_selected_final_issue", source_observations=[]) is True


def test_low_evidence_score_downgrades_to_needs_review_instead_of_drop() -> None:
    finding = agent_finding()
    scored = apply_evidence_score_policy(finding, {"score": 0.2, "components": {}}, {"drop_below": 0.35, "downgrade_below": 0.5})

    retained = retain_as_needs_review(
        scored,
        reason="evidence_score_below_drop_threshold",
        quality_trace=build_quality_trace(scored, []),
        source_observations=[],
        tool_provenance=[],
    )

    assert retained["selected"] == 0
    assert retained["judge_adjustment"] == "needs_review:evidence_score_below_drop_threshold"
    assert retained["quality_trace"]["judge"]["retained_reason"] == "evidence_score_below_drop_threshold"


def test_critic_rejected_still_allows_hard_drop() -> None:
    finding = agent_finding()
    trace = build_quality_trace(finding, [])
    trace["critic_verdict"] = {"verdict": "rejected", "reason": "source snippet does not support finding"}

    assert _critic_rejected({"quality_trace": trace}) is True


def test_secondary_test_advisory_never_prunes_critical_or_high_findings() -> None:
    findings = [
        agent_finding(
            dedupe_hash="test-critical",
            agent_id="test_agent",
            severity="critical",
            covered_rules=["TEST-COVER-001"],
            title="关键支付状态缺少并发回归测试",
        ),
        agent_finding(
            dedupe_hash="test-high",
            agent_id="test_agent",
            severity="high",
            covered_rules=["TEST-ASSERT-002"],
            title="安全校验测试没有断言拒绝结果",
        ),
        agent_finding(
            dedupe_hash="test-medium",
            agent_id="test_agent",
            severity="medium",
            covered_rules=["TEST-COVER-001"],
            title="普通边界测试覆盖建议",
        ),
    ]

    kept, rejected = _prune_low_signal_final_findings(findings)

    assert {item["dedupe_hash"] for item in kept} == {"test-critical", "test-high"}, (kept, rejected)
    assert [item["dedupe_hash"] for item in rejected] == ["test-medium"], rejected
    assert rejected[0]["rejected_reasons"] == ["secondary_test_advisory"], rejected


if __name__ == "__main__":
    test_agent_only_complete_finding_is_retained_without_tool_support()
    test_minimax_source_grounded_unattributed_finding_is_retained_for_review()
    test_unattributed_claim_without_location_or_source_evidence_is_rejectable()
    test_partial_evidence_contract_is_retained_as_needs_review()
    test_quality_trace_preserves_bound_evidence_contract()
    test_skill_checkpoint_rule_is_not_reconciled_to_tool_rule()
    test_bound_skill_merge_does_not_add_lower_priority_tool_rule()
    test_bound_skill_merge_uses_batch_label_when_checkpoint_field_missing()
    test_bound_skill_merge_recovers_retry_label_with_colon_checkpoint()
    test_bound_skill_merge_restores_authoritative_id_when_current_rules_are_dirty()
    test_bound_skill_merge_does_not_add_lower_priority_skipped_rule()
    test_business_semantic_dedupe_merges_cross_layer_audit_findings()
    test_same_root_cause_on_different_lines_is_not_deduped_lower_rank()
    test_unselected_structured_candidate_is_retained_for_review()
    test_low_evidence_score_downgrades_to_needs_review_instead_of_drop()
    test_critic_rejected_still_allows_hard_drop()
    test_secondary_test_advisory_never_prunes_critical_or_high_findings()
