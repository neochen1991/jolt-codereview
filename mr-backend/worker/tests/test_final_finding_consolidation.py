from __future__ import annotations

import json
import unittest

from orchestration.quality.final_consolidation import (
    CONTRACT_VERSION,
    compact_findings,
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


if __name__ == "__main__":
    test_compact_findings_assigns_stable_request_local_ids()
    test_parse_consolidation_response_accepts_valid_groups()
    test_parse_consolidation_response_rejects_invalid_groups_atomically()
    test_parse_consolidation_response_rejects_invalid_json()
    print("final finding consolidation contract tests passed")
