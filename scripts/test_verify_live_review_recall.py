from __future__ import annotations

from verify_live_review_recall import evaluate_live_review_recall


def _base_report() -> dict:
    return {
        "run_id": "run_live_1",
        "gold_findings": [
            {
                "id": "gold-1",
                "rule_id": "JAVA-ERR-001",
                "file_path": "src/Service.java",
                "line_start": 42,
                "severity": "high",
            }
        ],
        "final_findings": [
            {
                "id": "finding-1",
                "covered_rules": ["JAVA-ERR-001"],
                "file_path": "src/Service.java",
                "line_start": 44,
                "severity": "high",
            }
        ],
        "events": [
            {
                "event_type": "context_units_fallback",
                "payload": {"after": 3, "selected_files": ["a", "b", "c"]},
            }
        ],
        "candidate_decisions": [],
    }


def test_live_gate_accepts_matched_gold_and_bounded_fallback() -> None:
    result = evaluate_live_review_recall(_base_report())

    assert result["ok"] is True, result
    assert result["matched_gold_count"] == 1, result
    assert result["fallback_max_units"] == 3, result


def test_live_gate_reports_gold_lost_at_context_selection() -> None:
    report = _base_report()
    report["final_findings"] = []
    report["events"].append(
        {
            "event_type": "no_relevant_context_units",
            "payload": {"rule_ids": ["JAVA-ERR-001"], "batch_label": "error handling"},
        }
    )

    result = evaluate_live_review_recall(report)

    assert result["ok"] is False, result
    assert result["failures"][0]["code"] == "gold_lost_at_context", result
    assert result["failures"][0]["gold_id"] == "gold-1", result


def test_live_gate_rejects_high_severity_soft_drop_and_unclassified_drop() -> None:
    report = _base_report()
    report["candidate_decisions"] = [
        {
            "id": "candidate-soft",
            "status": "rejected",
            "severity": "critical",
            "rejected_reasons": ["secondary_test_advisory"],
        },
        {
            "id": "candidate-unknown",
            "status": "rejected",
            "severity": "medium",
            "rejected_reasons": ["judge_unclassified_rejection"],
        },
    ]

    result = evaluate_live_review_recall(report)

    codes = [item["code"] for item in result["failures"]]
    assert "high_severity_soft_rejection" in codes, result
    assert "judge_unclassified_rejection" in codes, result


def test_live_gate_rejects_unbounded_context_fallback() -> None:
    report = _base_report()
    report["events"] = [
        {
            "event_type": "context_units_fallback",
            "payload": {"after": 4, "selected_files": ["a", "b", "c", "d"]},
        }
    ]

    result = evaluate_live_review_recall(report)

    assert result["ok"] is False, result
    assert result["failures"][0]["code"] == "unbounded_context_fallback", result


if __name__ == "__main__":
    test_live_gate_accepts_matched_gold_and_bounded_fallback()
    test_live_gate_reports_gold_lost_at_context_selection()
    test_live_gate_rejects_high_severity_soft_drop_and_unclassified_drop()
    test_live_gate_rejects_unbounded_context_fallback()
