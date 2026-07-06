from __future__ import annotations

from render_real_pr_quality_report import render
from score_real_pr_reviews import evaluate


def test_render_includes_actionable_sections() -> None:
    gold = [
        {
            "id": "gold-auth",
            "mr_id": "mr-1",
            "file_path": "src/Auth.java",
            "line_start": 10,
            "rule_id": "SEC-AUTH-001",
            "severity": "high",
            "evidence_keywords": ["auth"],
        },
        {
            "id": "gold-sql",
            "mr_id": "mr-1",
            "file_path": "src/Sql.java",
            "line_start": 20,
            "rule_id": "SEC-INJECT-003",
            "severity": "high",
            "evidence_keywords": ["executeQuery"],
        },
        {"id": "gold-negative", "mr_id": "mr-negative", "ground_truth": "negative"},
    ]
    findings = [
        {
            "finding_id": "finding-auth",
            "mr_id": "mr-1",
            "file_path": "src/Auth.java",
            "line_start": 10,
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
            "quality_trace": {"evidence_score": {"score": 0.31, "components": {}}},
        },
    ]

    markdown = render(evaluate(gold, findings, 3), title="Test Report")

    assert "# Test Report" in markdown, markdown
    assert "## Action Items" in markdown, markdown
    assert "recall_gap" in markdown, markdown
    assert "precision_gap" in markdown, markdown
    assert "weak_evidence" in markdown, markdown
    assert "## Rule Gaps" in markdown, markdown
    assert "SEC-INJECT-003" in markdown, markdown
    assert "## MR Gaps" in markdown, markdown
    assert "mr-negative" in markdown, markdown
    assert "## Weak Evidence Findings" in markdown, markdown
    assert "finding-fp" in markdown, markdown


if __name__ == "__main__":
    test_render_includes_actionable_sections()
