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


def test_evaluate_reports_mr_level_and_actionable_quality_gaps() -> None:
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
        {
            "id": "gold-negative",
            "mr_id": "mr-negative",
            "ground_truth": "negative",
        },
    ]
    findings = [
        {
            "finding_id": "finding-auth",
            "mr_id": "mr-1",
            "file_path": "src/Auth.java",
            "line_start": 20,
            "title": "auth missing",
            "covered_rules": ["SEC-AUTH-001"],
            "quality_trace": {
                "evidence_score": {"score": 0.72, "components": {"tool_backing": 0.3}},
                "consensus_agents": ["security_agent"],
                "critic_verdict": {"verdict": "confirmed"},
            },
        },
        {
            "finding_id": "finding-fp",
            "mr_id": "mr-negative",
            "file_path": "src/Other.java",
            "line_start": 99,
            "title": "weak unrelated sql claim",
            "covered_rules": ["SEC-INJECT-003"],
            "quality_trace": {
                "evidence_score": {"score": 0.31, "components": {"tool_backing": 0.1}},
            },
        },
    ]

    report = evaluate(gold, findings, tolerance=3)

    assert report["by_mr"]["mr-1"]["tp"] == 1, report
    assert report["by_mr"]["mr-1"]["fn"] == 1, report
    assert report["by_mr"]["mr-1"]["recall"] == 0.5, report
    assert report["by_mr"]["mr-negative"]["is_negative"] is True, report
    assert report["by_mr"]["mr-negative"]["fp"] == 1, report
    assert report["by_mr"]["mr-negative"]["false_positive_finding_ids"] == ["finding-fp"], report
    assert report["quality_summary"]["evidence_score"]["below_0_50"] == 1, report
    assert report["quality_summary"]["missing_consensus_agents_count"] == 1, report
    assert report["quality_summary"]["missing_critic_verdict_count"] == 1, report
    weak_ids = [item["finding_id"] for item in report["quality_summary"]["weak_findings"]]
    assert weak_ids == ["finding-fp"], report
    action_types = {item["type"] for item in report["action_items"]}
    assert {"recall_gap", "precision_gap", "weak_evidence"}.issubset(action_types), report


def test_evaluate_is_stable_when_gold_order_changes() -> None:
    gold = [
        {
            "id": "gold-first",
            "mr_id": "mr-1",
            "file_path": "src/Auth.java",
            "line_start": 10,
            "rule_id": "SEC-AUTH-001",
            "severity": "high",
            "evidence_keywords": ["auth"],
        },
        {
            "id": "gold-second",
            "mr_id": "mr-1",
            "file_path": "src/Auth.java",
            "line_start": 20,
            "rule_id": "SEC-AUTH-001",
            "severity": "high",
            "evidence_keywords": ["auth"],
        },
    ]
    findings = [
        {
            "finding_id": "finding-near-first",
            "mr_id": "mr-1",
            "file_path": "src/Auth.java",
            "line_start": 15,
            "title": "auth missing",
            "covered_rules": ["SEC-AUTH-001"],
        },
        {
            "finding_id": "finding-exact-second",
            "mr_id": "mr-1",
            "file_path": "src/Auth.java",
            "line_start": 20,
            "title": "auth missing",
            "covered_rules": ["SEC-AUTH-001"],
        },
    ]

    original = evaluate(gold, findings, tolerance=5)
    reversed_gold = evaluate(list(reversed(gold)), findings, tolerance=5)

    assert original["tp"] == 2, original
    assert original["missed_gold_ids"] == [], original
    assert reversed_gold["tp"] == original["tp"], reversed_gold
    assert reversed_gold["missed_gold_ids"] == original["missed_gold_ids"], reversed_gold
    assert reversed_gold["false_positive_findings"] == original["false_positive_findings"], reversed_gold


if __name__ == "__main__":
    test_evaluate_uses_one_finding_for_one_gold_match()
    test_evaluate_reports_rule_level_precision_and_recall()
    test_evaluate_reports_mr_level_and_actionable_quality_gaps()
    test_evaluate_is_stable_when_gold_order_changes()
