from __future__ import annotations

import json
import unittest
from copy import deepcopy

from orchestration.quality.final_consolidation import (
    CONTRACT_VERSION,
    build_consolidation_prompt,
    compact_findings,
    consolidate_final_findings,
    merge_consolidation_groups,
    parse_consolidation_response,
)


def _findings() -> list[dict]:
    return [
        {
            "dedupe_hash": "finding-a",
            "agent_id": "backend_agent",
            "file_path": "src/RefundService.java",
            "line_start": 10,
            "line_end": 10,
            "title": "退款接口缺少幂等保护",
            "problem_description": "重复请求没有使用退款请求号去重，可能造成重复退款。",
            "recommendation": "使用 refundRequestId 建立唯一约束。",
            "evidence": "refund(request) 直接执行退款。",
            "covered_rules": ["BE-IDEMPOTENCY-001"],
        },
        {
            "dedupe_hash": "finding-b",
            "agent_id": "security_agent",
            "file_path": "src/RefundService.java",
            "line_start": 12,
            "line_end": 12,
            "title": "重复退款请求未防护",
            "problem_description": "相同 refundRequestId 可以重复触发退款。",
            "recommendation": "持久化退款请求号并拒绝重复处理。",
            "evidence": "gateway.refund(command) 没有幂等键。",
            "covered_rules": ["SEC-RISK-006"],
        },
    ]


def test_compact_findings_assigns_stable_request_local_ids() -> None:
    compact, lookup = compact_findings(_findings())

    assert [item["id"] for item in compact] == ["f_01", "f_02"]
    assert lookup["f_01"]["dedupe_hash"] == "finding-a"
    assert lookup["f_02"]["dedupe_hash"] == "finding-b"
    assert compact[0]["root_cause"] == _findings()[0]["problem_description"]
    assert compact[0]["impact"] == _findings()[0]["problem_description"]


def test_parse_consolidation_response_accepts_valid_groups() -> None:
    payload = {
        "version": CONTRACT_VERSION,
        "groups": [
            {
                "member_ids": ["f_01", "f_02"],
                "reason": "同一退款入口、同一幂等缺失根因和同一修复动作",
            }
        ],
    }

    groups, failure = parse_consolidation_response(json.dumps(payload, ensure_ascii=False), {"f_01", "f_02"})

    assert failure is None
    assert groups == payload["groups"]


def test_parse_consolidation_response_rejects_invalid_groups_atomically() -> None:
    cases = [
        ({"version": "future", "groups": []}, "invariant_violation"),
        (
            {"version": CONTRACT_VERSION, "groups": [{"member_ids": ["f_01", "f_99"], "reason": "same"}]},
            "unknown_member",
        ),
        (
            {"version": CONTRACT_VERSION, "groups": [{"member_ids": ["f_01", "f_01"], "reason": "same"}]},
            "overlapping_groups",
        ),
        ({"version": CONTRACT_VERSION, "groups": [{"member_ids": [], "reason": "same"}]}, "invariant_violation"),
        ({"version": CONTRACT_VERSION, "groups": [{"member_ids": ["f_01"], "reason": "same"}]}, "invariant_violation"),
        (
            {
                "version": CONTRACT_VERSION,
                "groups": [
                    {"member_ids": ["f_01", "f_02"], "reason": "same"},
                    {"member_ids": ["f_02", "f_03"], "reason": "same again"},
                ],
            },
            "overlapping_groups",
        ),
    ]
    for payload, reason in cases:
        with unittest.TestCase().subTest(reason=reason, payload=payload):
            groups, failure = parse_consolidation_response(json.dumps(payload), {"f_01", "f_02", "f_03"})

            assert groups == []
            assert failure is not None
            assert failure.reason == reason


def test_parse_consolidation_response_rejects_invalid_json() -> None:
    groups, failure = parse_consolidation_response("not-json", {"f_01", "f_02"})

    assert groups == []
    assert failure is not None
    assert failure.reason == "invalid_json"


def test_merge_consolidation_groups_preserves_trusted_fields_and_provenance() -> None:
    first, second = _findings()
    first.update(
        {
            "severity": "medium",
            "confidence": 0.91,
            "suggested_code": "first-fix",
            "source_observations": [{"tool_name": "semgrep", "rule_id": "rule-a"}],
            "tool_provenance": [{"tool_name": "semgrep", "rule_id": "rule-a"}],
            "quality_trace": {"existing": "first"},
        }
    )
    second.update(
        {
            "severity": "high",
            "confidence": 0.87,
            "suggested_code": "second-fix",
            "verification_flags": ["tool_promoted"],
            "source_observations": [
                {"tool_name": "semgrep", "rule_id": "rule-a"},
                {"tool_name": "java_web_static", "rule_id": "rule-b"},
            ],
            "tool_provenance": [{"tool_name": "java_web_static", "rule_id": "rule-b"}],
            "quality_trace": {"existing": "second"},
        }
    )
    original = deepcopy([first, second])

    merged, rejected = merge_consolidation_groups(
        [first, second],
        [{"member_ids": ["f_01", "f_02"], "reason": "same idempotency root cause"}],
        model_metadata={"provider": "test", "model": "semantic-model", "duration_ms": 17},
    )

    assert [first, second] == original
    assert len(merged) == 1
    primary = merged[0]
    assert primary["title"] == second["title"]
    assert primary["problem_description"] == second["problem_description"]
    assert primary["recommendation"] == second["recommendation"]
    assert primary["suggested_code"] == "second-fix"
    assert primary["severity"] == "high"
    assert primary["confidence"] == 0.91
    assert primary["covered_rules"] == ["BE-IDEMPOTENCY-001", "SEC-RISK-006"]
    assert primary["merged_agent_ids"] == ["backend_agent", "security_agent"]
    assert primary["related_locations"] == [
        {"file_path": "src/RefundService.java", "line_start": 10, "line_end": 10}
    ]
    assert "refund(request)" in primary["evidence"]
    assert "gateway.refund" in primary["evidence"]
    assert len(primary["source_observations"]) == 2
    assert len(primary["tool_provenance"]) == 2
    assert primary["dedupe_hash"].startswith("issue_v2_")
    trace = primary["quality_trace"]["final_consolidation"]
    assert trace["member_hashes"] == ["finding-a", "finding-b"]
    assert trace["primary_member_hash"] == "finding-b"
    assert trace["reason"] == "same idempotency root cause"
    assert trace["merged_count"] == 2
    assert trace["model"] == "semantic-model"
    assert rejected == [
        {
            **first,
            "rejected_reasons": ["deduped_final_llm_consolidation"],
            "merged_into_dedupe_hash": primary["dedupe_hash"],
        }
    ]


def test_merge_consolidation_groups_never_increases_count_and_keeps_ungrouped_findings() -> None:
    findings = [*_findings(), {**_findings()[0], "dedupe_hash": "finding-c", "title": "独立问题"}]

    merged, rejected = merge_consolidation_groups(
        findings,
        [{"member_ids": ["f_01", "f_02"], "reason": "same root cause"}],
    )

    assert len(merged) == 2
    assert len(merged) <= len(findings)
    assert any(item["title"] == "独立问题" for item in merged)
    assert len(rejected) == 1


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple] = []
        self.calls: list[dict] = []
        self.run_id = "run-final-consolidation"

    def event(self, *args, **kwargs) -> None:
        self.events.append((*args, kwargs))

    def llm_call(self, *args, **kwargs) -> None:
        self.calls.append({"args": args, "kwargs": kwargs})


class _StoppedBudget:
    truncated_reason = "max_llm_calls"

    def should_stop(self) -> bool:
        return True


def _enabled_config(**overrides) -> dict:
    return {
        "review_quality": {
            "final_consolidation": {
                "enabled": True,
                "min_findings": 2,
                "max_findings": 30,
                "timeout_seconds": 45,
                "max_output_tokens": 4096,
                "temperature": 0,
                "fail_open": True,
                **overrides,
            }
        }
    }


def test_build_consolidation_prompt_forbids_new_or_rewritten_findings() -> None:
    compact, _ = compact_findings(_findings())

    prompt = build_consolidation_prompt(compact)

    assert "只能合并" in prompt
    assert "不能新增" in prompt
    assert "不能删除" in prompt
    assert "不能改写" in prompt
    assert "SQL 注入" in prompt
    assert "无界查询" in prompt
    assert "缺少测试" in prompt


def test_consolidate_final_findings_applies_valid_model_groups() -> None:
    prompts: list[str] = []

    result = consolidate_final_findings(
        findings=_findings(),
        config=_enabled_config(),
        recorder=_Recorder(),
        span_id="judge-span",
        head_sha="head-1",
        consolidation_llm=lambda prompt: prompts.append(prompt)
        or {
            "version": CONTRACT_VERSION,
            "groups": [{"member_ids": ["f_01", "f_02"], "reason": "same idempotency issue"}],
        },
    )

    assert len(prompts) == 1
    assert len(result.findings) == 1
    assert len(result.rejections) == 1
    assert result.fallback_reason is None
    assert result.metadata["operation"] == "final_consolidation"
    assert result.metadata["input_finding_count"] == 2
    assert result.metadata["output_finding_count"] == 1


def test_consolidate_final_findings_skips_disabled_small_or_budget_stopped_inputs() -> None:
    calls: list[str] = []
    cases = [
        ({"review_quality": {"final_consolidation": {"enabled": False}}}, _findings(), None, "disabled"),
        (_enabled_config(), [_findings()[0]], None, "below_min_findings"),
        (_enabled_config(), _findings(), _StoppedBudget(), "budget_exhausted"),
    ]
    for config, findings, budget, reason in cases:
        result = consolidate_final_findings(
            findings=findings,
            config=config,
            recorder=_Recorder(),
            span_id="judge-span",
            head_sha="head-1",
            budget_tracker=budget,
            consolidation_llm=lambda prompt: calls.append(prompt) or {},
        )
        assert result.findings == findings
        assert result.rejections == []
        assert result.fallback_reason == reason
    assert calls == []


def test_consolidate_final_findings_fails_open_on_invalid_output_or_exception() -> None:
    for llm, reason in [
        (lambda _prompt: "not-json", "invalid_json"),
        (
            lambda _prompt: {
                "version": CONTRACT_VERSION,
                "groups": [{"member_ids": ["f_01", "f_99"], "reason": "unknown"}],
            },
            "unknown_member",
        ),
        (lambda _prompt: (_ for _ in ()).throw(TimeoutError("slow")), "timeout"),
        (lambda _prompt: (_ for _ in ()).throw(RuntimeError("offline")), "provider_unavailable"),
    ]:
        findings = _findings()
        result = consolidate_final_findings(
            findings=findings,
            config=_enabled_config(),
            recorder=_Recorder(),
            span_id="judge-span",
            head_sha="head-1",
            consolidation_llm=llm,
        )
        assert result.findings == findings
        assert result.rejections == []
        assert result.fallback_reason == reason


if __name__ == "__main__":
    test_compact_findings_assigns_stable_request_local_ids()
    test_parse_consolidation_response_accepts_valid_groups()
    test_parse_consolidation_response_rejects_invalid_groups_atomically()
    test_parse_consolidation_response_rejects_invalid_json()
    test_merge_consolidation_groups_preserves_trusted_fields_and_provenance()
    test_merge_consolidation_groups_never_increases_count_and_keeps_ungrouped_findings()
    test_build_consolidation_prompt_forbids_new_or_rewritten_findings()
    test_consolidate_final_findings_applies_valid_model_groups()
    test_consolidate_final_findings_skips_disabled_small_or_budget_stopped_inputs()
    test_consolidate_final_findings_fails_open_on_invalid_output_or_exception()
    print("final finding consolidation contract tests passed")
