from __future__ import annotations

from score_real_pr_reviews import evaluate


def test_evaluate_uses_one_finding_for_one_gold_match() -> None:
    gold = [
        {
            "id": "gold-auth-1",
            "mr_id": "mr-1",
            "file_path": "src/App.java",
            "line_start": 10,
            "rule_id": "SEC-AUTH-001",
            "evidence_keywords": ["auth"],
        },
        {
            "id": "gold-auth-2",
            "mr_id": "mr-1",
            "file_path": "src/App.java",
            "line_start": 11,
            "rule_id": "SEC-AUTH-001",
            "evidence_keywords": ["auth"],
        },
    ]
    findings = [
        {
            "mr_id": "mr-1",
            "file_path": "src/App.java",
            "line_start": 10,
            "title": "auth missing",
            "covered_rules": ["SEC-AUTH-001"],
        }
    ]

    report = evaluate(gold, findings, tolerance=5)

    assert report["tp"] == 1, report
    assert report["fn"] == 1, report
    assert report["recall"] == 0.5, report
    assert report["missed_gold_ids"] == ["gold-auth-2"], report


def test_evaluate_reports_rule_level_precision_and_recall() -> None:
    gold = [
        {
            "id": "gold-auth",
            "mr_id": "mr-1",
            "file_path": "src/Auth.java",
            "line_start": 20,
            "rule_id": "SEC-AUTH-001",
            "severity": "high",
            "evidence_keywords": ["auth"],
        },
        {
            "id": "gold-sql",
            "mr_id": "mr-1",
            "file_path": "src/Sql.java",
            "line_start": 30,
            "rule_id": "SEC-INJECT-003",
            "severity": "high",
            "evidence_keywords": ["executeQuery"],
        },
    ]
    findings = [
        {
            "mr_id": "mr-1",
            "file_path": "src/Auth.java",
            "line_start": 20,
            "title": "auth missing",
            "covered_rules": ["SEC-AUTH-001"],
        },
        {
            "mr_id": "mr-1",
            "file_path": "src/Other.java",
            "line_start": 99,
            "title": "unrelated sql claim",
            "covered_rules": ["SEC-INJECT-003"],
        },
    ]

    report = evaluate(gold, findings, tolerance=3)

    assert report["by_rule"]["SEC-AUTH-001"]["tp"] == 1, report
    assert report["by_rule"]["SEC-AUTH-001"]["recall"] == 1.0, report
    assert report["by_rule"]["SEC-INJECT-003"]["fn"] == 1, report
    assert report["by_rule"]["SEC-INJECT-003"]["fp"] == 1, report
    assert report["by_rule"]["SEC-INJECT-003"]["precision"] == 0.0, report
    assert report["by_rule"]["SEC-INJECT-003"]["missed_gold_ids"] == ["gold-sql"], report


if __name__ == "__main__":
    test_evaluate_uses_one_finding_for_one_gold_match()
    test_evaluate_reports_rule_level_precision_and_recall()
