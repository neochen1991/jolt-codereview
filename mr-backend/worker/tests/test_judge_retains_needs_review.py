from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

from orchestration.judging.evidence_score import apply_evidence_score_policy
from orchestration.nodes.judge_findings import (
    _critic_rejected,
    _merge_finding_metadata,
    build_quality_trace,
    reconcile_rules_with_tool_observations,
    retain_as_needs_review,
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


if __name__ == "__main__":
    test_agent_only_complete_finding_is_retained_without_tool_support()
    test_partial_evidence_contract_is_retained_as_needs_review()
    test_quality_trace_preserves_bound_evidence_contract()
    test_skill_checkpoint_rule_is_not_reconciled_to_tool_rule()
    test_bound_skill_merge_does_not_add_lower_priority_tool_rule()
    test_bound_skill_merge_uses_batch_label_when_checkpoint_field_missing()
    test_bound_skill_merge_recovers_retry_label_with_colon_checkpoint()
    test_low_evidence_score_downgrades_to_needs_review_instead_of_drop()
    test_critic_rejected_still_allows_hard_drop()
