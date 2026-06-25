from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

from orchestration.judging.evidence_score import changed_line_index, score, snippet_hash


PATCH = """@@ -0,0 +40,4 @@
+public void search(String userId) {
+  String sql = "select * from payment where user_id = " + userId;
+  ResultSet rs = statement.executeQuery(sql);
+}
"""


def finding(**overrides: object) -> dict:
    item = {
        "agent_id": "security_agent",
        "severity": "high",
        "confidence": 0.9,
        "file_path": "src/main/java/demo/PaymentRepository.java",
        "line_start": 42,
        "line_end": 42,
        "covered_rules": ["SEC-INJECT-003"],
        "evidence": 'String sql = "select * from payment where user_id = " + userId; ResultSet rs = statement.executeQuery(sql);',
    }
    item.update(overrides)
    return item


def test_evidence_score_components_are_structural() -> None:
    files = [SimpleNamespace(filename="src/main/java/demo/PaymentRepository.java", patch=PATCH)]
    line_index = changed_line_index(files)
    tool_observations = [
        {
            "tool_name": "java_web_static",
            "rule_id": "JOLT_JAVA_SQL_CONCAT",
            "confidence": 0.9,
            "file_path": "src/main/java/demo/PaymentRepository.java",
            "line_start": 42,
        }
    ]
    source_observations = [{"rule_id": "SEC-INJECT-003", "promoted_rule": "SEC-INJECT-003"}]
    related_context = {
        "changed_symbols": [
            {"file_path": "src/main/java/demo/PaymentRepository.java", "line_start": 42, "name": "search"}
        ]
    }
    peer = [
        finding(agent_id="security_agent"),
        finding(agent_id="database_agent"),
    ]
    result = score(
        finding(),
        line_index=line_index,
        related_context=related_context,
        tool_observations=tool_observations,
        source_observations=source_observations,
        peer_findings=peer,
    )
    components = result["components"]
    assert components["tool_backing"] > 0, result
    assert components["snippet_quote"] > 0, result
    assert components["line_precision"] == 0.1, result
    assert components["rule_alignment"] == 0.1, result
    assert components["symbol_alignment"] == 0.15, result
    assert components["consensus"] == 0.15, result
    assert result["score"] >= 0.8, result


def test_evidence_score_uses_line_span_not_rule_specific_branch() -> None:
    files = [SimpleNamespace(filename="src/main/java/demo/PaymentRepository.java", patch=PATCH)]
    result = score(
        finding(line_start=1, line_end=40, evidence="unrelated evidence that is long enough but not in source"),
        files=files,
        tool_observations=[],
        source_observations=[],
        peer_findings=[finding(line_start=1, line_end=40)],
    )
    assert result["components"]["tool_backing"] == 0, result
    assert result["components"]["snippet_quote"] == 0, result
    assert result["components"]["line_precision"] == 0, result
    assert result["score"] <= 0.15, result


def test_suppression_hint_reduces_evidence_score_without_rule_branch() -> None:
    files = [SimpleNamespace(filename="src/main/java/demo/PaymentRepository.java", patch=PATCH)]
    base = score(finding(), files=files, peer_findings=[finding()])
    suppressed = score(
        finding(),
        files=files,
        peer_findings=[finding()],
        suppression_hints=[
            {
                "rule_id": "SEC-INJECT-003",
                "file_glob": "src/main/**",
                "snippet_hash": "not-a-match",
                "count": 99,
            },
            {
                "rule_id": "SEC-INJECT-003",
                "file_glob": "src/main/**",
                "snippet_hash": snippet_hash(finding()["evidence"]),
                "count": 3,
                "snippet_excerpt": finding()["evidence"],
            },
        ],
    )
    assert suppressed["score"] < base["score"], (base, suppressed)
    assert suppressed["suppression_penalty"] > 0, suppressed
    assert suppressed["matched_suppression_hint"]["rule_id"] == "SEC-INJECT-003", suppressed


if __name__ == "__main__":
    test_evidence_score_components_are_structural()
    test_evidence_score_uses_line_span_not_rule_specific_branch()
    test_suppression_hint_reduces_evidence_score_without_rule_branch()
