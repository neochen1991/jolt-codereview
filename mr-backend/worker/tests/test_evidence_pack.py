from __future__ import annotations

import sys
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

from orchestration.judging.evidence_pack import build_evidence_pack  # noqa: E402


def _finding(**overrides):
    item = {
        "file_path": "src/AuthService.java",
        "line_start": 42,
        "line_end": 42,
        "title": "missing authorization guard",
        "problem_description": "caller reaches update without authorization",
        "evidence": "update(request.getTenantId())",
        "trigger_condition": "an untrusted tenant id is submitted",
        "impact": "an attacker can update another tenant",
        "severity": "high",
        "confidence": 0.9,
        "context_hash": "ctx-1",
    }
    item.update(overrides)
    return item


def test_strong_typed_path_and_trigger_is_confirmed() -> None:
    pack = build_evidence_pack(
        _finding(),
        semantic_paths=[{"edges": [{"confidence": "typed"}, {"confidence": "syntax"}], "complete": True}],
        context_health={"status": "full"},
    )
    assert pack.status == "confirmed"
    assert pack.semantic_path_strength >= 0.8
    assert pack.trigger_specificity >= 0.7


def test_local_high_severity_with_location_trigger_and_impact_is_confirmed() -> None:
    pack = build_evidence_pack(
        _finding(),
        semantic_paths=[],
        context_health={"status": "full"},
    )
    assert pack.status == "confirmed"


def test_heuristic_same_name_relation_needs_review() -> None:
    pack = build_evidence_pack(
        _finding(),
        semantic_paths=[{"edges": [{"confidence": "heuristic", "reason": "same_name_regex"}], "complete": False}],
        context_health={"status": "partial"},
    )
    assert pack.status == "needs_review"
    assert "heuristic_semantic_path" in pack.reason_codes


def test_contradicting_guard_rejects_with_explicit_reason() -> None:
    pack = build_evidence_pack(
        _finding(),
        semantic_paths=[{"edges": [{"confidence": "typed"}], "complete": True}],
        contradictions=[{"kind": "authorization_guard", "evidence": "permissionService.requireAdmin(user)"}],
        context_health={"status": "full"},
    )
    assert pack.status == "rejected_with_reason"
    assert pack.contradiction_penalty >= 0.6
    assert "contradicting_authorization_guard" in pack.reason_codes


def test_missing_context_is_unresolved_not_silently_dropped() -> None:
    pack = build_evidence_pack(
        _finding(context_hash="", evidence=""),
        semantic_paths=[],
        context_health={"status": "patch_only", "context_units_unresolved": 1},
    )
    assert pack.status == "unresolved_context"
    assert "context_incomplete" in pack.reason_codes


def test_high_severity_without_impact_path_cannot_be_confirmed() -> None:
    pack = build_evidence_pack(
        _finding(impact=""),
        semantic_paths=[{"edges": [{"confidence": "typed"}], "complete": True}],
        context_health={"status": "full"},
    )
    assert pack.status == "needs_review"
    assert "impact_missing" in pack.reason_codes


def test_bound_rule_with_no_required_evidence_and_no_tool_support_is_rejected() -> None:
    pack = build_evidence_pack(
        _finding(
            title="gRPC version upgrade compatibility suggestion",
            problem_description="The upgrade is usually compatible, but protobuf compatibility should be checked.",
            evidence="grpc.version changed from 1.81.0 to 1.82.1",
            trigger_condition="protobuf versions are incompatible",
            impact="potential serialization compatibility issue",
            severity="medium",
            covered_rules=["DEP-LICENSE-002"],
            bound_evidence_contract={
                "status": "weak",
                "matched_required_evidence": [],
                "missing_required_evidence": ["license conflict evidence"],
            },
        ),
        semantic_paths=[],
        tool_observations=[],
        context_health={"status": "full"},
    )
    assert pack.status == "rejected_with_reason"
    assert "bound_required_evidence_missing" in pack.reason_codes


if __name__ == "__main__":
    test_strong_typed_path_and_trigger_is_confirmed()
    test_local_high_severity_with_location_trigger_and_impact_is_confirmed()
    test_heuristic_same_name_relation_needs_review()
    test_contradicting_guard_rejects_with_explicit_reason()
    test_missing_context_is_unresolved_not_silently_dropped()
    test_high_severity_without_impact_path_cannot_be_confirmed()
    test_bound_rule_with_no_required_evidence_and_no_tool_support_is_rejected()
    print("evidence pack tests passed")
