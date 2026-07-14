from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from review_quality_rollback import (
    build_rollback_payload,
    runtime_safety_decision,
)


def rows(statuses: list[str]) -> list[dict]:
    return [
        {"merge_request_id": f"mr-{index}", "status": status, "context_health_status": "full"}
        for index, status in enumerate(statuses)
    ]


def test_three_consecutive_failures_trigger_immediate_rollback() -> None:
    decision = runtime_safety_decision(rows(["failed", "dead_letter", "failed", "no_issue"]))
    assert decision["rollback_required"] is True
    assert decision["trigger"] == "three_consecutive_failures"


def test_more_than_twenty_percent_failures_in_ten_distinct_mrs_rolls_back() -> None:
    decision = runtime_safety_decision(rows(["failed", "no_issue", "failed", "no_issue", "failed", "no_issue", "no_issue", "no_issue", "no_issue", "no_issue"]))
    assert decision["rollback_required"] is True
    assert decision["trigger"] == "failure_rate_exceeded"
    assert decision["failure_rate"] == 0.3
    assert decision["distinct_mr_count"] == 10


def test_two_failures_in_ten_and_partial_window_do_not_roll_back() -> None:
    safe = runtime_safety_decision(rows(["failed", "no_issue", "no_issue", "failed", "no_issue", "no_issue", "no_issue", "no_issue", "no_issue", "no_issue"]))
    assert safe["rollback_required"] is False
    partial = runtime_safety_decision(rows(["failed", "no_issue", "failed", "no_issue"]))
    assert partial["rollback_required"] is False
    assert partial["trigger"] == "insufficient_runtime_window"


def test_blocked_context_counts_as_runtime_failure() -> None:
    sample = rows(["no_issue"] * 10)
    for index in (0, 3, 6):
        sample[index]["context_health_status"] = "blocked"
    decision = runtime_safety_decision(sample)
    assert decision["rollback_required"] is True
    assert decision["failed_count"] == 3


def test_rollback_payload_is_narrow_and_auditable() -> None:
    decision = runtime_safety_decision(rows(["failed", "dead_letter", "failed"]))
    payload = build_rollback_payload("project-1", decision, source_run_id="run-1")
    assert payload["target_context_engine"] == "v1"
    assert payload["trigger"] == "three_consecutive_failures"
    assert payload["source_run_id"] == "run-1"
    assert payload["evidence"]["failed_count"] == 3
    assert "requested_at" in payload


if __name__ == "__main__":
    test_three_consecutive_failures_trigger_immediate_rollback()
    test_more_than_twenty_percent_failures_in_ten_distinct_mrs_rolls_back()
    test_two_failures_in_ten_and_partial_window_do_not_roll_back()
    test_blocked_context_counts_as_runtime_failure()
    test_rollback_payload_is_narrow_and_auditable()
