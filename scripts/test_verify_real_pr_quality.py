from __future__ import annotations

from types import SimpleNamespace

from verify_real_pr_quality import report_threshold_failures


def test_report_threshold_failures_catches_rule_and_positive_mr_regressions() -> None:
    report = {
        "high_severity_accuracy": 1.0,
        "mr_count": 2,
        "gold_count": 10,
        "negative_mr_count": 1,
        "quality_summary": {"weak_findings": []},
        "by_rule": {
            "SEC-AUTH-001": {
                "gold_count": 5,
                "finding_count": 5,
                "precision": 1.0,
                "recall": 1.0,
            },
            "SEC-INJECT-003": {
                "gold_count": 5,
                "finding_count": 5,
                "precision": 0.6,
                "recall": 0.4,
            },
        },
        "by_mr": {
            "mr-positive": {
                "is_negative": False,
                "gold_count": 5,
                "finding_count": 5,
                "precision": 0.7,
                "recall": 0.6,
            },
            "mr-negative": {
                "is_negative": True,
                "gold_count": 0,
                "finding_count": 0,
                "precision": 0.0,
                "recall": 0.0,
            },
        },
    }
    args = SimpleNamespace(
        min_high_severity_accuracy=0.8,
        min_mrs=1,
        min_gold=10,
        min_negative_mrs=1,
        max_weak_evidence=0,
        min_rule_precision=0.8,
        min_rule_recall=0.65,
        min_mr_precision=0.8,
        min_mr_recall=0.65,
    )

    failures = report_threshold_failures(report, args)

    assert "rule SEC-INJECT-003 precision 0.6 < 0.8" in failures
    assert "rule SEC-INJECT-003 recall 0.4 < 0.65" in failures
    assert "mr mr-positive precision 0.7 < 0.8" in failures
    assert "mr mr-positive recall 0.6 < 0.65" in failures
    assert not any("mr-negative" in failure for failure in failures)


if __name__ == "__main__":
    test_report_threshold_failures_catches_rule_and_positive_mr_regressions()
