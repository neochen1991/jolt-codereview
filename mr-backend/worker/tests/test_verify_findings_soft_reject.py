from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

from diff.slicer import source_snippet_loader_for_files
from orchestration.nodes.verify_findings import _evidence_matches_source, _token_jaccard, verify_candidate_findings


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

    def test_source_context_window_includes_nearby_diff_context(self):
        class ChangedFile:
            filename = "src/PaymentController.java"
            patch = """@@ -20,21 +20,21 @@ public List<Order> listOrders() {
     public List<Order> listOrders() {
         validateTenant();
         if (!currentUser.canReadOrders()) {
             throw new ForbiddenException();
         }
         String tenantId = currentTenant();
         audit("listOrders", tenantId);
         OrderFilter filter = OrderFilter.forTenant(tenantId);
         List<Order> orders = repository.findAll(filter);
         enrichOrders(orders);
         redactInternalNotes(orders);
         attachTags(orders);
         attachRiskFlags(orders);
         attachOwnerInfo(orders);
         attachPaymentState(orders);
         attachShipmentState(orders);
         attachRefundState(orders);
         attachInvoiceState(orders);
         attachPromotionState(orders);
+        metrics.record("orders.list");
         return orders;
     }"""

        finding = {
            **self.base_finding("List<Order> orders = repository.findAll(filter);", confidence=0.91),
            "agent_id": "performance_agent",
            "file_path": "src/PaymentController.java",
            "line_start": 39,
            "title": "查询缺少分页或结果上限",
            "problem_description": "同一方法内调用 repository.findAll(filter) 取全量订单，新增路径没有分页边界。",
            "covered_rules": ["PERF-QUERY-001"],
        }
        accepted, rejected = verify_candidate_findings(
            [finding],
            {"src/PaymentController.java"},
            {"performance_agent": {"min_confidence": 0.75}},
            set(),
            {"src/PaymentController.java": [(39, 39)]},
            {"PERF-QUERY-001"},
            source_snippet_loader_for_files([ChangedFile()]),
        )
        self.assertEqual(rejected, [])
        self.assertEqual(len(accepted), 1)
        self.assertNotIn("low_evidence_match", accepted[0].get("verification_flags") or [])

    def test_evidence_score_high_accepts(self):
        finding = self.base_finding("ResultSet rs = statement.executeQuery(sql)")
        accepted, rejected = self.verify(finding, "ResultSet rs = statement.executeQuery(sql);")
        self.assertEqual(len(accepted), 1)
        self.assertEqual(rejected, [])
        self.assertGreaterEqual(_evidence_matches_source(finding["evidence"], "ResultSet rs = statement.executeQuery(sql);")["score"], 0.5)

    def test_chinese_evidence_token_similarity_uses_ngrams(self):
        score = _token_jaccard("订单状态缺少校验", "订单状态没有进行服务端校验")
        self.assertGreaterEqual(score, 0.2)

    def test_chinese_evidence_token_similarity_handles_synonyms(self):
        auth_score = _token_jaccard("接口缺少鉴权", "接口没有进行权限校验直接执行管理员操作")
        state_score = _token_jaccard("客户端可控状态直接覆盖订单状态，缺少服务端策略约束", "直接使用客户端传入状态更新订单状态，没有服务端校验")
        unrelated_score = _token_jaccard("接口缺少权限校验", "金额使用浮点构造导致精度问题")
        self.assertGreaterEqual(auth_score, 0.35)
        self.assertGreaterEqual(state_score, 0.35)
        self.assertLess(unrelated_score, 0.2)

    def test_chinese_semantic_similarity_does_not_match_same_domain_non_issues(self):
        auth_false_positive = _token_jaccard("接口缺少鉴权", "接口权限控制页面展示管理员操作记录")
        state_false_positive = _token_jaccard("客户端可控状态直接覆盖订单状态", "客户端传入订单状态用于查询筛选，没有修改订单状态")
        self.assertLess(auth_false_positive, 0.35)
        self.assertLess(state_false_positive, 0.35)

    def test_chinese_sql_injection_evidence_matches_code_semantics(self):
        result = _evidence_matches_source(
            "这里直接把外部输入拼接进 SQL 并执行，存在注入风险。",
            'String sql = "select * from payment where user_id = " + userId;\nResultSet rs = statement.executeQuery(sql);',
        )
        self.assertGreaterEqual(result["score"], 0.5, result)

    def test_sql_execution_without_concat_does_not_match_injection_semantics(self):
        result = _evidence_matches_source(
            "这里直接把外部输入拼接进 SQL 并执行，存在注入风险。",
            "ResultSet rs = statement.executeQuery(sql);",
        )
        self.assertLess(result["score"], 0.5, result)

    def test_chinese_state_update_evidence_matches_code_semantics(self):
        result = _evidence_matches_source(
            "客户端传入状态直接覆盖订单状态，缺少服务端状态流转校验。",
            "payment.setStatus(request.getStatus());",
        )
        self.assertGreaterEqual(result["score"], 0.5, result)

    def test_chinese_command_injection_evidence_matches_code_semantics(self):
        result = _evidence_matches_source(
            "用户输入被拼接进系统命令后直接执行，存在命令注入风险。",
            'Runtime.getRuntime().exec("sh -c " + request.getParameter("cmd"));',
        )
        self.assertGreaterEqual(result["score"], 0.5, result)

    def test_constant_command_execution_does_not_match_injection_semantics(self):
        result = _evidence_matches_source(
            "用户输入被拼接进系统命令后直接执行，存在命令注入风险。",
            'Runtime.getRuntime().exec("uptime");',
        )
        self.assertLess(result["score"], 0.5, result)

    def test_chinese_path_traversal_evidence_matches_code_semantics(self):
        result = _evidence_matches_source(
            "请求参数直接参与文件路径读取，缺少路径规范化和目录限制。",
            "return Files.readString(Paths.get(baseDir, request.getParameter(\"name\")));",
        )
        self.assertGreaterEqual(result["score"], 0.5, result)

    def test_constant_file_read_does_not_match_path_traversal_semantics(self):
        result = _evidence_matches_source(
            "请求参数直接参与文件路径读取，缺少路径规范化和目录限制。",
            'return Files.readString(Paths.get(baseDir, "README.md"));',
        )
        self.assertLess(result["score"], 0.5, result)

    def test_chinese_log_leak_evidence_matches_code_semantics(self):
        result = _evidence_matches_source(
            "敏感 token 被直接打印到日志，可能泄露凭证。",
            'logger.info("login token={}", accessToken);',
        )
        self.assertGreaterEqual(result["score"], 0.5, result)

    def test_chinese_sensitive_response_matches_code_identifier_semantics(self):
        result = _evidence_matches_source(
            "用户手机号未脱敏直接返回给前端。",
            "return user.getPhoneNumber();",
        )
        self.assertGreaterEqual(result["score"], 0.5, result)

    def test_masked_sensitive_response_does_not_match_missing_mask_claim(self):
        result = _evidence_matches_source(
            "用户手机号未脱敏直接返回给前端。",
            "return mask(user.getPhoneNumber());",
        )
        self.assertLess(result["score"], 0.5, result)

    def test_chinese_redis_missing_ttl_matches_write_without_expire(self):
        result = _evidence_matches_source(
            "Redis key 写入缓存时没有设置过期时间。",
            "redisTemplate.opsForValue().set(key, value);",
        )
        self.assertGreaterEqual(result["score"], 0.5, result)

    def test_redis_write_with_expire_does_not_match_missing_ttl_claim(self):
        result = _evidence_matches_source(
            "Redis key 写入缓存时没有设置过期时间。",
            "redisTemplate.opsForValue().set(key, value, Duration.ofMinutes(5)); redisTemplate.expire(key, ttl);",
        )
        self.assertLess(result["score"], 0.5, result)

    def test_non_sensitive_log_does_not_match_secret_leak_semantics(self):
        result = _evidence_matches_source(
            "敏感 token 被直接打印到日志，可能泄露凭证。",
            'logger.info("login success for user {}", userId);',
        )
        self.assertLess(result["score"], 0.5, result)

    def test_chinese_resource_leak_evidence_matches_code_semantics(self):
        result = _evidence_matches_source(
            "打开输入流后没有关闭资源，可能导致文件句柄泄露。",
            "InputStream in = new FileInputStream(path); return in.read();",
        )
        self.assertGreaterEqual(result["score"], 0.5, result)

    def test_closed_resource_does_not_match_resource_leak_semantics(self):
        result = _evidence_matches_source(
            "打开输入流后没有关闭资源，可能导致文件句柄泄露。",
            "try (InputStream in = new FileInputStream(path)) { return in.read(); }",
        )
        self.assertLess(result["score"], 0.5, result)

    def test_chinese_bigdecimal_precision_evidence_matches_code_semantics(self):
        result = _evidence_matches_source(
            "金额使用 double 构造 BigDecimal，可能产生精度问题。",
            "BigDecimal total = new BigDecimal(amount.doubleValue());",
        )
        self.assertGreaterEqual(result["score"], 0.5, result)

    def test_evidence_score_middle_lowers_confidence_and_flags(self):
        finding = {
            **self.base_finding("executeQuery SQL userId injection", confidence=0.8),
            "title": "SQL 查询风险待确认",
            "problem_description": "SQL 执行上下文证据不足。",
        }
        accepted, rejected = self.verify(finding, "ResultSet rs = statement.executeQuery(sql);")
        self.assertEqual(rejected, [])
        self.assertEqual(len(accepted), 1)
        self.assertIn("low_evidence_match", accepted[0]["verification_flags"])
        self.assertAlmostEqual(accepted[0]["confidence"], 0.75)
        self.assertGreaterEqual(accepted[0]["evidence_match_score"], 0.2)
        self.assertLess(accepted[0]["evidence_match_score"], 0.5)

    def test_paraphrased_evidence_on_source_location_is_flagged_not_rejected(self):
        finding = self.base_finding("这里直接把外部输入拼接进 SQL 并执行，存在注入风险。", confidence=0.91)
        accepted, rejected = self.verify(finding, "ResultSet rs = statement.executeQuery(sql + userId);")
        self.assertEqual(rejected, [])
        self.assertEqual(len(accepted), 1)
        self.assertNotIn("low_evidence_match", accepted[0].get("verification_flags") or [])

    def test_paraphrased_evidence_on_generic_source_location_is_flagged_not_rejected(self):
        finding = {
            **self.base_finding("这里直接复用客户端传入的状态覆盖服务端状态，缺少业务上下文校验。", confidence=0.91),
            "title": "客户端可控状态直接覆盖订单状态",
            "problem_description": "外部请求字段直接驱动状态变更，缺少服务端策略约束。",
            "covered_rules": ["CODE-STATE-004"],
        }
        accepted, rejected = self.verify(finding, "payment.setStatus(request.getStatus());")
        self.assertEqual(rejected, [])
        self.assertEqual(len(accepted), 1)
        self.assertNotIn("low_evidence_match", accepted[0].get("verification_flags") or [])

    def test_evidence_score_low_with_missing_source_window_is_flagged_not_rejected(self):
        finding = self.base_finding("totally unrelated payment gateway timeout retry", confidence=0.91)
        accepted, rejected = self.verify(finding, "")
        self.assertEqual(rejected, [])
        self.assertEqual(len(accepted), 1)
        self.assertIn("low_evidence_match", accepted[0]["verification_flags"])
        self.assertIn("source_window_missing", accepted[0]["verification_flags"])

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
