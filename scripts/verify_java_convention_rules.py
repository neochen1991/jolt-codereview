from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from orchestration.nodes.judge_findings import promote_tool_observations
from tools.java_web_static_tool import scan_java_web_files


@dataclass
class ChangedFile:
    filename: str
    patch: str


def _patch(*lines: str) -> str:
    return "\n".join(["@@ -0,0 +1,200 @@", *[f"+{line}" for line in lines]])


def main() -> None:
    files = [
        ChangedFile(
            "src/main/java/com/jolt/payment/controller/PaymentController.java",
            _patch(
                "package com.jolt.payment.controller;",
                "import java.util.Map;",
                "import org.springframework.web.bind.annotation.PostMapping;",
                "import org.springframework.web.bind.annotation.RequestBody;",
                "import org.springframework.web.bind.annotation.RestController;",
                "import com.jolt.payment.repository.PaymentRepository;",
                "@RestController",
                "public class PaymentController {",
                "    private final PaymentRepository paymentRepository;",
                "    public PaymentController(PaymentRepository paymentRepository) {",
                "        this.paymentRepository = paymentRepository;",
                "    }",
                "    @PostMapping(\"/payments\")",
                "    public Map<String, Object> create(@RequestBody Map<String, Object> payload) throws Exception {",
                "        Thread.sleep(1000);",
                "        paymentRepository.save(payload);",
                "        return payload;",
                "    }",
                "}",
            ),
        ),
        ChangedFile(
            "src/main/java/com/jolt/payment/service/_PaymentService.java",
            _patch(
                "package com.jolt.payment.service;",
                "import java.math.BigDecimal;",
                "import java.text.SimpleDateFormat;",
                "import java.util.Collections;",
                "import java.util.List;",
                "import java.util.Objects;",
                "import java.util.Random;",
                "import java.util.concurrent.Executors;",
                "import org.springframework.stereotype.Service;",
                "import org.springframework.transaction.annotation.Transactional;",
                "@Service",
                "public class _PaymentService {",
                "    private static final SimpleDateFormat FORMAT = new SimpleDateFormat(\"yyyy-MM-dd\");",
                "    private final Random tokenRandom = new Random();",
                "    public BigDecimal fee() {",
                "        return new BigDecimal(0.1);",
                "    }",
                "    public void asyncAudit() {",
                "        Executors.newFixedThreadPool(100);",
                "    }",
                "    @Transactional",
                "    private void savePayment() {",
                "        System.out.println(\"saved\");",
                "    }",
                "    public List<String> listOrders() {",
                "        try {",
                "            throw new IllegalStateException(\"boom\");",
                "        } catch (Exception e) {",
                "            e.printStackTrace();",
                "            return null;",
                "        }",
                "    }",
                "    @Override",
                "    public boolean equals(Object other) {",
                "        return Objects.equals(this.toString(), other.toString());",
                "    }",
                "}",
            ),
        ),
        ChangedFile(
            "src/main/java/com/jolt/payment/controller/LegacyAutowiredController.java",
            _patch(
                "package com.jolt.payment.controller;",
                "import org.springframework.beans.factory.annotation.Autowired;",
                "import org.springframework.web.bind.annotation.RestController;",
                "@RestController",
                "public class LegacyAutowiredController {",
                "    @Autowired",
                "    private PaymentService paymentService;",
                "}",
            ),
        ),
        ChangedFile(
            "src/main/java/com/jolt/payment/controller/ConstructorAutowiredController.java",
            _patch(
                "package com.jolt.payment.controller;",
                "import org.springframework.beans.factory.annotation.Autowired;",
                "import org.springframework.web.bind.annotation.RestController;",
                "@RestController",
                "public class ConstructorAutowiredController {",
                "    private final PaymentService paymentService;",
                "    @Autowired",
                "    public ConstructorAutowiredController(PaymentService paymentService) {",
                "        this.paymentService = paymentService;",
                "    }",
                "}",
            ),
        ),
        ChangedFile(
            "src/main/java/com/jolt/payment/service/StatusComparisonService.java",
            _patch(
                "package com.jolt.payment.service;",
                "public class StatusComparisonService {",
                "    public boolean paid(String status) {",
                "        return \"PAID\".equals(status);",
                "    }",
                "}",
            ),
        ),
        ChangedFile(
            "src/main/java/com/jolt/payment/application/PaymentDddApplicationService.java",
            _patch(
                "package com.jolt.payment.application;",
                "import com.jolt.payment.domain.PaymentOrder;",
                "import com.jolt.payment.domain.PaymentStatus;",
                "import com.jolt.payment.repository.PaymentRepository;",
                "public class PaymentDddApplicationService {",
                "    private final PaymentRepository paymentRepository;",
                "    public void forceTransition(String paymentId, String merchantId, String nextStatus) {",
                "        PaymentOrder order = paymentRepository.find(paymentId);",
                "        order.setMerchantId(merchantId);",
                "        order.setStatus(PaymentStatus.valueOf(nextStatus));",
                "        paymentRepository.save(order);",
                "    }",
                "}",
            ),
        ),
        ChangedFile(
            "src/main/java/com/jolt/payment/domain/PaymentRepository.java",
            _patch(
                "package com.jolt.payment.domain;",
                "import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;",
                "import java.util.List;",
                "public interface PaymentRepository {",
                "    List<PaymentOrder> query(QueryWrapper<PaymentEntity> wrapper);",
                "}",
            ),
        ),
        ChangedFile(
            "src/main/java/com/jolt/payment/domain/event/PayOrderEvent.java",
            _patch(
                "package com.jolt.payment.domain.event;",
                "import com.jolt.payment.domain.PaymentOrder;",
                "public record PayOrderEvent(PaymentOrder order) {}",
            ),
        ),
        ChangedFile(
            "src/main/java/com/jolt/payment/service/ChineseNamingService.java",
            _patch(
                "package com.jolt.payment.service;",
                "public class ChineseNamingService {",
                "    private String 用户名 = \"zhangsan\";",
                "}",
            ),
        ),
        ChangedFile(
            "src/main/java/com/jolt/payment/security/TokenFactory.java",
            _patch(
                "package com.jolt.payment.security;",
                "import java.util.Random;",
                "public class TokenFactory {",
                "    private final Random tokenRandom = new Random();",
                "}",
            ),
        ),
        ChangedFile(
            "src/main/resources/mapper/PaymentMapper.xml",
            _patch(
                "<?xml version=\"1.0\" encoding=\"UTF-8\" ?>",
                "<mapper namespace=\"PaymentMapper\">",
                "  <select id=\"findByUser\" resultType=\"java.util.HashMap\">",
                "    SELECT * FROM payment WHERE user_id = ${userId}",
                "  </select>",
                "  <select id=\"pageLegacy\">",
                "    queryForList(\"PaymentMapper.findByUser\", start, size)",
                "  </select>",
                "</mapper>",
            ),
        ),
        ChangedFile(
            "src/test/java/com/jolt/payment/PaymentServiceTest.java",
            _patch(
                "package com.jolt.payment;",
                "class PaymentServiceTest {}",
            ),
        ),
    ]

    findings = scan_java_web_files(files, head_sha="verify-java-convention")
    rules = {str(item.get("tool_rule_id")) for item in findings}
    expected_rules = {
        "ALI-BIGDECIMAL-001",
        "ALI-CONCURRENCY-001",
        "ALI-CONCURRENCY-002",
        "ALI-DB-001",
        "ALI-DB-002",
        "ALI-EQUALS-001",
        "ALI-EXC-002",
        "ALI-LOG-001",
        "ALI-MYBATIS-001",
        "ALI-NAMING-001",
        "ALI-NAMING-002",
        "ALI-RETURN-001",
        "BE-API-001",
        "BE-IDEMP-004",
        "DDD-AGG-002",
        "DDD-EVENT-001",
        "DDD-EVENT-002",
        "DDD-REPO-002",
        "HW-LAYER-001",
        "HW-PERF-001",
        "HW-SEC-001",
        "HW-TX-001",
    }
    missing = sorted(expected_rules - rules)
    assert not missing, {"missing_rules": missing, "actual_rules": sorted(rules)}
    assert not any(
        item.get("tool_rule_id") == "JOLT_JAVA_FIELD_AUTOWIRED"
        for item in findings
    ), "@Autowired field injection rule should not be reported"
    assert not any(
        item.get("tool_rule_id") == "ALI-EQUALS-001"
        and item.get("file_path") == "src/main/java/com/jolt/payment/service/StatusComparisonService.java"
        for item in findings
    ), "ordinary equals() calls should not be reported as equals/hashCode override violations"

    observations: list[dict[str, Any]] = [
        {
            "tool_name": "java_web_static",
            "rule_id": item.get("tool_rule_id"),
            "severity": item.get("severity"),
            "confidence": item.get("confidence"),
            "file_path": item.get("file_path"),
            "line_start": item.get("line_start"),
            "line_end": item.get("line_end"),
            "message": item.get("problem_description"),
        }
        for item in findings
        if item.get("tool_rule_id") in expected_rules
    ]
    promoted = promote_tool_observations(observations, [])
    promoted_rules = {str(item.get("tool_rule_id")) for item in promoted}
    assert expected_rules <= promoted_rules, {
        "missing_promotions": sorted(expected_rules - promoted_rules),
        "promoted_rules": sorted(promoted_rules),
    }
    assert any(item.get("agent_id") == "security_agent" and item.get("tool_rule_id") == "ALI-MYBATIS-001" for item in promoted)
    assert any(item.get("agent_id") == "performance_agent" and item.get("tool_rule_id") == "HW-PERF-001" for item in promoted)
    assert all(item.get("suggested_code") for item in promoted)

    print(
        json.dumps(
            {
                "status": "ok",
                "detected_rule_count": len(rules),
                "expected_rule_count": len(expected_rules),
                "promoted_rule_count": len(promoted_rules),
                "rules": sorted(expected_rules),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
