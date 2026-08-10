from __future__ import annotations

from types import SimpleNamespace

from verify_intent_aware_precision import derive_duplicate_groups, score_labeled_cases, score_scope_violations


def test_score_reports_precision_recall_and_false_positive_breakdown() -> None:
    report = score_labeled_cases(
        [
            {"case_id": "tp-high", "expected": True, "published": True, "severity": "high", "intent": "mixed", "category": "SQL_INJECTION"},
            {"case_id": "fn-high", "expected": True, "published": False, "severity": "high", "intent": "behavior_change", "category": "AUTHORIZATION_BYPASS"},
            {"case_id": "fp-safe", "expected": False, "published": True, "severity": "medium", "intent": "logging_only", "category": "BROAD_EXCEPTION"},
            {"case_id": "tn-safe", "expected": False, "published": False, "severity": "medium", "intent": "rename_or_move", "category": "NULL_SAFETY"},
        ]
    )

    assert report["precision"] == 0.5, report
    assert report["recall"] == 0.5, report
    assert report["high_severity_recall"] == 0.5, report
    assert report["false_positives_by_intent"] == {"logging_only": 1}, report
    assert report["false_positives_by_category"] == {"BROAD_EXCEPTION": 1}, report
    assert report["duplicate_group_count"] == 0, report


def test_duplicate_groups_are_derived_from_finding_semantics() -> None:
    findings = [
        {
            "finding_id": "auth-a",
            "agent_id": "security_agent",
            "file_path": "src/Auth.java",
            "line_start": 12,
            "title": "缺少权限验证",
            "problem_description": "更新前未鉴权。",
            "evidence": "repository.update(request)",
            "covered_rules": ["SEC-AUTH-001"],
        },
        {
            "finding_id": "auth-b",
            "agent_id": "backend_agent",
            "file_path": "src/Auth.java",
            "line_start": 12,
            "title": "接口没有鉴权保护",
            "problem_description": "调用更新方法前没有授权判断。",
            "evidence": "repository.update(request)",
            "covered_rules": ["BE-API-001"],
        },
    ]

    groups = derive_duplicate_groups(findings)
    report = score_labeled_cases([], findings=findings)

    assert groups == [["auth-a", "auth-b"]], groups
    assert report["duplicate_group_count"] == 1, report
    assert report["duplicate_rate"] == 0.5, report


def test_scope_metrics_count_off_diff_and_unchanged_files() -> None:
    files = [
        SimpleNamespace(
            filename="src/Auth.java",
            patch="@@ -10,1 +10,2 @@\n old();\n+changed();",
        )
    ]
    findings = [
        {"finding_id": "on", "file_path": "src/Auth.java", "line_start": 11, "selected": 1, "severity": "high"},
        {"finding_id": "old", "file_path": "src/Auth.java", "line_start": 10, "selected": 1, "severity": "high"},
        {"finding_id": "other", "file_path": "src/Other.java", "line_start": 11, "selected": 1, "severity": "high"},
    ]

    metrics = score_scope_violations(findings, files)

    assert metrics["off_diff_published_count"] == 1, metrics
    assert metrics["unchanged_file_published_count"] == 1, metrics
    assert metrics["automatic_relocation_count"] == 0, metrics


if __name__ == "__main__":
    test_score_reports_precision_recall_and_false_positive_breakdown()
    test_duplicate_groups_are_derived_from_finding_semantics()
    test_scope_metrics_count_off_diff_and_unchanged_files()
    print("intent-aware precision scorer tests passed")
