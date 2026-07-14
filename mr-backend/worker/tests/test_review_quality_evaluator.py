from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from review_quality_evaluator import (
    evaluate_labeled_pairs,
    validate_gold_records,
)


def approved_gold(mr_id: str, index: int, *, disagreement: bool = False, reason: str = "") -> dict:
    return {
        "id": f"gold-{index}",
        "mr_id": mr_id,
        "file": "src/Service.java",
        "line": 10 + index,
        "rule_id": "SEC-AUTH-001",
        "severity": "high",
        "cross_file": True,
        "review": {
            "reviewer_1": {"id": "alice", "verdict": "valid"},
            "reviewer_2": {"id": "bob", "verdict": "invalid" if disagreement else "valid"},
            "status": "approved",
            "adjudication_reason": reason,
        },
    }


def pair(mr_id: str, *, v1_hit: bool, v2_hit: bool) -> dict:
    finding = {
        "id": f"finding-{mr_id}",
        "mr_id": mr_id,
        "file_path": "src/Service.java",
        "line_start": 10 + int(mr_id.split("-")[-1]),
        "covered_rules": ["SEC-AUTH-001"],
        "title": "missing auth",
    }
    return {
        "merge_request_id": mr_id,
        "v1_findings": [finding] if v1_hit else [],
        "v2_findings": [finding] if v2_hit else [],
        "v1_tokens": 100,
        "v2_tokens": 120,
        "v1_duration_ms": 1000,
        "v2_duration_ms": 1100,
    }


def test_gold_requires_two_distinct_reviewers_and_disagreement_reason() -> None:
    invalid = approved_gold("mr-1", 1, disagreement=True)
    errors = validate_gold_records([invalid])
    assert any("adjudication_reason" in error for error in errors)
    invalid["review"]["adjudication_reason"] = "reviewed runtime evidence"
    invalid["review"]["reviewer_2"]["id"] = "alice"
    errors = validate_gold_records([invalid])
    assert any("distinct reviewer" in error for error in errors)


def test_less_than_thirty_distinct_paired_mrs_stays_provisional() -> None:
    gold = [approved_gold(f"mr-{index}", index) for index in range(1, 30)]
    pairs = [pair(f"mr-{index}", v1_hit=False, v2_hit=True) for index in range(1, 30)]
    report = evaluate_labeled_pairs(gold, pairs)
    assert report["validation_status"] == "provisional"
    assert "minimum_30_distinct_paired_mrs" in report["missing_evidence"]


def test_complete_thirty_mr_uplift_is_verified() -> None:
    gold = [approved_gold(f"mr-{index}", index) for index in range(1, 31)]
    pairs = [pair(f"mr-{index}", v1_hit=index <= 20, v2_hit=index <= 29) for index in range(1, 31)]
    report = evaluate_labeled_pairs(gold, pairs)
    assert report["validation_status"] == "verified", report
    assert report["candidate"]["recall"] > report["baseline"]["recall"]
    assert report["candidate"]["precision"] >= report["baseline"]["precision"] - 0.02


def test_missing_cost_is_not_allowed_to_pass_quality_gate() -> None:
    gold = [approved_gold(f"mr-{index}", index) for index in range(1, 31)]
    pairs = [pair(f"mr-{index}", v1_hit=index <= 20, v2_hit=index <= 29) for index in range(1, 31)]
    pairs[0].pop("v2_tokens")
    report = evaluate_labeled_pairs(gold, pairs)
    assert report["validation_status"] == "provisional"
    assert "complete_paired_cost_data" in report["missing_evidence"]


def test_fully_evidenced_non_uplift_requests_rollback() -> None:
    gold = [approved_gold(f"mr-{index}", index) for index in range(1, 31)]
    pairs = [pair(f"mr-{index}", v1_hit=index <= 25, v2_hit=index <= 25) for index in range(1, 31)]
    report = evaluate_labeled_pairs(gold, pairs)
    assert report["validation_status"] == "rollback_required"
    assert any(check["metric"] == "recall_uplift" and not check["passed"] for check in report["gate"]["checks"])


if __name__ == "__main__":
    test_gold_requires_two_distinct_reviewers_and_disagreement_reason()
    test_less_than_thirty_distinct_paired_mrs_stays_provisional()
    test_complete_thirty_mr_uplift_is_verified()
    test_missing_cost_is_not_allowed_to_pass_quality_gate()
    test_fully_evidenced_non_uplift_requests_rollback()
