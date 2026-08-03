from __future__ import annotations

from verify_intent_aware_precision import score_labeled_cases


def test_score_reports_precision_recall_and_false_positive_breakdown() -> None:
    report = score_labeled_cases(
        [
            {"case_id": "tp-high", "expected": True, "published": True, "severity": "high", "intent": "mixed", "category": "SQL_INJECTION"},
            {"case_id": "fn-high", "expected": True, "published": False, "severity": "high", "intent": "behavior_change", "category": "AUTHORIZATION_BYPASS"},
            {"case_id": "fp-safe", "expected": False, "published": True, "severity": "medium", "intent": "logging_only", "category": "BROAD_EXCEPTION"},
            {"case_id": "tn-safe", "expected": False, "published": False, "severity": "medium", "intent": "rename_or_move", "category": "NULL_SAFETY"},
        ],
        duplicate_groups=[["fp-safe", "fp-safe-copy"]],
    )

    assert report["precision"] == 0.5, report
    assert report["recall"] == 0.5, report
    assert report["high_severity_recall"] == 0.5, report
    assert report["false_positives_by_intent"] == {"logging_only": 1}, report
    assert report["false_positives_by_category"] == {"BROAD_EXCEPTION": 1}, report
    assert report["duplicate_group_count"] == 1, report


if __name__ == "__main__":
    test_score_reports_precision_recall_and_false_positive_breakdown()
    print("intent-aware precision scorer tests passed")
