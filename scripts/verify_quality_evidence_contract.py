from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "worker"
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from orchestration.nodes.finalize import summarize_evidence_contracts
from orchestration.nodes.judge_findings import build_evidence_contract, build_quality_trace, is_publishable_evidence_contract


def main() -> None:
    source_observation = {
        "tool_name": "tree_sitter_code_graph",
        "rule_id": "SEC-INJECT-003",
        "file_path": "src/main/java/demo/PaymentRepository.java",
        "line_start": 42,
        "line_end": 42,
        "confidence": 0.91,
        "message": "SQL execution uses concatenated expression",
    }
    complete_finding = {
        "agent_id": "security_agent",
        "severity": "high",
        "confidence": 0.92,
        "dedupe_hash": "hash_sql_injection",
        "file_path": "src/main/java/demo/PaymentRepository.java",
        "line_start": 42,
        "line_end": 42,
        "title": "SQL 拼接存在注入风险",
        "problem_description": "新增查询使用字符串拼接外部输入。",
        "recommendation": "使用 PreparedStatement 或 MyBatis #{} 参数绑定。",
        "suggested_code": "PreparedStatement ps = connection.prepareStatement(sql);",
        "evidence": "String sql = \"select * from t where id = \" + userId;",
        "covered_rules": ["SEC-INJECT-003"],
    }
    contract = build_evidence_contract(complete_finding, [source_observation])
    assert contract["status"] == "satisfied", contract
    assert contract["score"] == 1.0, contract
    assert contract["missing"] == [], contract
    assert contract["source_type"] == "hybrid", contract
    assert contract["decision_hint"] == "final_candidate", contract

    trace = build_quality_trace(complete_finding, [source_observation])
    assert trace["evidence_contract"]["status"] == "satisfied", trace
    assert trace["tools"][0]["tool_name"] == "tree_sitter_code_graph", trace
    assert is_publishable_evidence_contract(trace), trace

    weak_finding = {
        "agent_id": "coding_agent",
        "severity": "medium",
        "confidence": 0.8,
        "dedupe_hash": "hash_weak",
        "file_path": "src/main/java/demo/Foo.java",
        "line_start": None,
        "title": "上下文不足的问题",
        "problem_description": "缺少定位和建议。",
        "recommendation": "",
        "suggested_code": "",
        "evidence": "",
        "covered_rules": [],
    }
    weak_trace = build_quality_trace(weak_finding, [])
    assert weak_trace["evidence_contract"]["status"] == "weak", weak_trace
    assert weak_trace["evidence_contract"]["decision_hint"] == "needs_review", weak_trace
    assert "has_location" in weak_trace["evidence_contract"]["missing"], weak_trace
    assert "has_rule" in weak_trace["evidence_contract"]["missing"], weak_trace
    assert not is_publishable_evidence_contract(weak_trace), weak_trace

    no_rule_finding = {
        **complete_finding,
        "dedupe_hash": "hash_no_rule",
        "title": "VARCHAR(32) 长度可能不足",
        "covered_rules": [],
        "rule_id": "VARCHAR(32) 长度可能不足",
        "tool_rule_id": "",
    }
    no_rule_trace = build_quality_trace(no_rule_finding, [source_observation])
    assert no_rule_trace["evidence_contract"]["status"] != "satisfied", no_rule_trace
    assert "has_rule" in no_rule_trace["evidence_contract"]["missing"], no_rule_trace
    assert not is_publishable_evidence_contract(no_rule_trace), no_rule_trace

    summary = summarize_evidence_contracts(
        [
            {"quality_trace": trace},
            {"quality_trace": json.dumps(weak_trace, ensure_ascii=False)},
        ]
    )
    assert summary["finding_count"] == 2, summary
    assert summary["contract_count"] == 2, summary
    assert summary["status_counts"]["satisfied"] == 1, summary
    assert summary["status_counts"]["weak"] == 1, summary
    assert summary["findings_missing_rule"] == 1, summary
    assert summary["findings_missing_suggested_code"] == 1, summary
    assert summary["complete_contract_rate"] == 0.5, summary
    assert summary["weak_contract_count"] == 1, summary
    assert summary["quality_risk"] == "needs_attention", summary

    frontend = (ROOT / "src/frontend/main.tsx").read_text(encoding="utf-8")
    assert "formatEvidenceContractStatus" in frontend
    assert "qualityTrace.evidence_contract" in frontend

    print("Quality evidence contract checks passed.")


if __name__ == "__main__":
    main()
