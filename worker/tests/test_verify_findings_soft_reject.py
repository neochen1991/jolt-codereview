from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

from orchestration.nodes.verify_findings import _evidence_matches_source, verify_candidate_findings


class VerifyFindingsSoftRejectTest(unittest.TestCase):
    def base_finding(self, evidence: str, confidence: float = 0.8) -> dict:
        return {
            "agent_id": "security_agent",
            "severity": "high",
            "confidence": confidence,
            "dedupe_hash": "hash",
            "file_path": "src/PaymentController.java",
            "line_start": 33,
            "title": "SQL 拼接存在注入风险",
            "problem_description": "外部输入被拼接进 SQL",
            "evidence": evidence,
            "covered_rules": ["SEC-INJECT-003"],
        }

    def verify(self, finding: dict, source: str):
        return verify_candidate_findings(
            [finding],
            {"src/PaymentController.java"},
            {"security_agent": {"min_confidence": 0.75}},
            set(),
            {"src/PaymentController.java": [(30, 36)]},
            {"SEC-INJECT-003"},
            lambda _file, _line, window=5: source,
        )

    def test_evidence_score_high_accepts(self):
        finding = self.base_finding("ResultSet rs = statement.executeQuery(sql)")
        accepted, rejected = self.verify(finding, "ResultSet rs = statement.executeQuery(sql);")
        self.assertEqual(len(accepted), 1)
        self.assertEqual(rejected, [])
        self.assertGreaterEqual(_evidence_matches_source(finding["evidence"], "ResultSet rs = statement.executeQuery(sql);")["score"], 0.5)

    def test_evidence_score_middle_lowers_confidence_and_flags(self):
        finding = self.base_finding("executeQuery SQL userId injection", confidence=0.8)
        accepted, rejected = self.verify(finding, "ResultSet rs = statement.executeQuery(sql + userId);")
        self.assertEqual(rejected, [])
        self.assertEqual(len(accepted), 1)
        self.assertIn("low_evidence_match", accepted[0]["verification_flags"])
        self.assertAlmostEqual(accepted[0]["confidence"], 0.75)
        self.assertGreaterEqual(accepted[0]["evidence_match_score"], 0.2)
        self.assertLess(accepted[0]["evidence_match_score"], 0.5)

    def test_evidence_score_low_rejects(self):
        finding = self.base_finding("totally unrelated payment gateway timeout retry", confidence=0.91)
        accepted, rejected = self.verify(finding, "ResultSet rs = statement.executeQuery(sql + userId);")
        self.assertEqual(accepted, [])
        self.assertEqual(rejected[0]["rejected_reasons"], ["evidence_not_in_source"])

    def test_bigdecimal_string_constructor_rejects_double_constructor_claim(self):
        finding = {
            **self.base_finding("new BigDecimal(\"1000.0\")", confidence=0.9),
            "title": "金额使用 double 构造 BigDecimal 导致精度问题",
            "problem_description": "这里使用 new BigDecimal(double) 构造金额。",
            "covered_rules": ["ALI-BIGDECIMAL-001"],
        }
        accepted, rejected = self.verify(finding, 'boolean matched = order.getAmount().equals(new BigDecimal("1000.0"));')
        self.assertEqual(accepted, [])
        self.assertIn("source_contradicts_bigdecimal_double_constructor", rejected[0]["rejected_reasons"])

    def test_return_null_claim_rejected_when_source_has_no_return_null(self):
        finding = {
            **self.base_finding("return Map.of(\"ok\", true);", confidence=0.9),
            "title": "Map 返回 null 导致调用方 NPE",
            "problem_description": "方法异常时 return null。",
            "covered_rules": ["CODE-NULL-001"],
        }
        accepted, rejected = self.verify(finding, 'return Map.of("ok", true);')
        self.assertEqual(accepted, [])
        self.assertIn("source_contradicts_return_null", rejected[0]["rejected_reasons"])

    def test_first_element_claim_rejected_when_source_has_empty_guard(self):
        finding = {
            **self.base_finding("orders.get(0)", confidence=0.9),
            "title": "候选订单首元素未判空",
            "problem_description": "直接 get(0) 未检查集合为空。",
            "covered_rules": ["CODE-NULL-001"],
        }
        source = """
        if (orders.isEmpty()) {
            throw new NotFoundException();
        }
        PaymentOrder order = orders.get(0);
        """
        accepted, rejected = self.verify(finding, source)
        self.assertEqual(accepted, [])
        self.assertIn("source_has_empty_guard_for_first_element", rejected[0]["rejected_reasons"])


if __name__ == "__main__":
    unittest.main()
