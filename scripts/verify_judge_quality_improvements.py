#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mr-backend" / "worker"))

fake_deepagents_runner = types.ModuleType("orchestration.deepagents_runner")
fake_deepagents_runner.run_bounded_deepagent = lambda **_kwargs: {"tool_calls": [], "content": ""}
sys.modules.setdefault("orchestration.deepagents_runner", fake_deepagents_runner)

from review_runtime import ChangedFile, run_external_static_prescan  # noqa: E402
from orchestration.nodes.judge_findings import (  # noqa: E402
    judge_candidate_findings,
    promote_tool_observations,
    supplement_bound_rule_findings,
)


class Recorder:
    def event(self, *_args, **_kwargs):
        return None

    def tool_call(self, *_args, **_kwargs):
        return None


def java_file(path: str, source: str) -> ChangedFile:
    lines = source.splitlines()
    return ChangedFile(
        filename=path,
        status="modified",
        additions=len(lines),
        deletions=0,
        changes=len(lines),
        patch="\n".join(["@@ -0,0 +1,1 @@", *[f"+{line}" for line in lines]]),
    )


def test_judge_merges_specific_canonical_rules_without_losing_business_rule() -> None:
    findings = [
        {
            "agent_id": "backend_agent",
            "severity": "medium",
            "confidence": 0.81,
            "dedupe_hash": "external-timeout",
            "file_path": "src/main/java/com/acme/settlement/service/SettlementPayoutService.java",
            "line_start": 38,
            "line_end": 38,
            "title": "PayoutGateway 外部调用未设置超时，事务内阻塞影响可靠性",
            "problem_description": "forcePay 标注 @Transactional 后立即执行 payoutGateway.payOut。",
            "evidence": "repository.save(ledger);\nPayoutReceipt receipt = payoutGateway.payOut(merchantId, amount);",
            "covered_rules": ["BE-INTEGRATION-006"],
        },
        {
            "agent_id": "backend_agent",
            "severity": "high",
            "confidence": 0.9,
            "dedupe_hash": "tx-external",
            "file_path": "src/main/java/com/acme/settlement/service/SettlementPayoutService.java",
            "line_start": 38,
            "line_end": 38,
            "title": "事务内调用外部打款网关",
            "problem_description": "@Transactional 方法 forcePay 内调用 payoutGateway.payOut，数据库事务会跨外部 I/O。",
            "evidence": "@Transactional\nrepository.save(ledger);\npayoutGateway.payOut(merchantId, amount);",
            "covered_rules": ["BE-TX-002"],
            "verification_flags": ["tool_promoted"],
            "tool_name": "java_web_static",
            "source_tool_observation": {"rule_id": "BE-TX-002", "tool_name": "java_web_static"},
        },
    ]
    final, rejected = judge_candidate_findings(findings, [], max_findings=5)
    assert any("BE-TX-002" in item.get("covered_rules", []) for item in final), (final, rejected)
    assert any("BE-INTEGRATION-006" in item.get("covered_rules", []) for item in final), (final, rejected)
    assert any("事务内调用外部打款网关" in item.get("title", "") for item in final), final


def test_bound_rule_supplement_filters_generic_anchor_only_rule() -> None:
    source = """package com.acme.settlement.api;
import org.springframework.web.bind.annotation.RestController;

@RestController
class SettlementAdminController {
  void forcePay() {}
}
"""
    supplements = supplement_bound_rule_findings(
        [java_file("src/main/java/com/acme/settlement/api/SettlementAdminController.java", source)],
        [
            {
                "agent_id": "ddd_agent",
                "bound_rules": [
                    {
                        "rule_id": "DDD-LAYER-001",
                        "title": "Controller 不能直接访问 Repository/Mapper",
                        "severity": "medium",
                        "check": "Controller 不能直接访问 Repository/Mapper。",
                        "negative_examples": "`@RestController class DemoController { private DemoRepository repository; }`",
                        "required_evidence": "必须展示 Controller 直接调用 Repository/Mapper 的代码。",
                    }
                ],
            }
        ],
        [],
    )
    assert supplements == [], supplements


def test_tool_observation_canonical_mapping_preserves_expected_rule_ids() -> None:
    observations = [
        {
            "tool_name": "java_web_static",
            "rule_id": "BE-INTEGRATION-006",
            "severity": "high",
            "confidence": 0.88,
            "file_path": "src/main/java/com/acme/settlement/service/SettlementPayoutService.java",
            "line_start": 38,
            "message": "@Transactional forcePay calls payoutGateway.payOut inside the transaction.",
        },
        {
            "tool_name": "semgrep",
            "rule_id": "ALI-CONCURRENCY-003",
            "severity": "high",
            "confidence": 0.86,
            "file_path": "src/main/java/com/acme/settlement/service/SettlementPayoutService.java",
            "line_start": 32,
            "message": "ThreadLocal CURRENT_TENANT.set is not followed by remove().",
        },
    ]
    promoted = promote_tool_observations(observations, [])
    covered = {rule for item in promoted for rule in item.get("covered_rules", [])}
    assert "BE-TX-002" in covered, promoted
    assert "CODE-STATE-004" in covered, promoted


def test_java_static_rules_cover_rare_business_patterns() -> None:
    controller = """package com.acme.settlement.api;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

class SettlementAdminController {
  private final SettlementPayoutService payoutService;
  @PostMapping("/force-pay")
  public Map<String, Object> forcePay(@RequestBody Map<String, Object> payload) {
    return payoutService.forcePay(String.valueOf(payload.get("tenantId")), String.valueOf(payload.get("merchantId")));
  }
  @PostMapping("/bulk-risk")
  public Map<String, Object> bulkRisk(@RequestBody List<String> settlementIds) {
    return payoutService.refreshRiskScores(settlementIds);
  }
}
"""
    service = """package com.acme.settlement.service;
import java.util.List;
import java.util.Map;
import org.springframework.transaction.annotation.Transactional;

class SettlementPayoutService {
  private static final ThreadLocal<String> CURRENT_TENANT = new ThreadLocal<>();
  private final PayoutGateway payoutGateway;
  private final RiskClient riskClient;
  private final SettlementRepository repository;

  @Transactional
  public Map<String, Object> forcePay(String tenantId, String merchantId) {
    CURRENT_TENANT.set(tenantId);
    repository.save(new Object());
    PayoutReceipt receipt = payoutGateway.payOut(merchantId);
    return Map.of("cardNo", receipt.cardNo(), "trace", receipt.rawGatewayMessage());
  }

  public Map<String, Object> refreshRiskScores(List<String> settlementIds) {
    for (String settlementId : settlementIds) {
      riskClient.fetchScore(settlementId);
    }
    return Map.of();
  }

  public List<Object> exportAll() {
    return repository.findAll().stream().toList();
  }
}
"""
    sources = {
        "src/main/java/com/acme/settlement/api/SettlementAdminController.java": controller,
        "src/main/java/com/acme/settlement/service/SettlementPayoutService.java": service,
    }
    files = [java_file(path, source) for path, source in sources.items()]
    import tempfile

    with tempfile.TemporaryDirectory(prefix="jolt-rare-java-rules-") as temp_dir:
        _summary, findings = run_external_static_prescan(
            Recorder(),
            "span_rare_java_rules",
            Path(temp_dir),
            files,
            "head_rare_java_rules",
            None,
            None,
            {
                "tool_policy": {
                    "enabled_tools": ["java-web-static", "tree-sitter"],
                    "static_runners": {"tree_sitter_code_graph": {"timeout_seconds": 5}},
                }
            },
            sources,
        )
    covered = {rule for item in findings for rule in item.get("covered_rules", [])}
    for expected in ["BE-IDEMP-004", "BE-API-001", "BE-TX-002", "SEC-SECRET-004", "PERF-QUERY-001", "CODE-STATE-004", "PERF-MEM-004"]:
        assert expected in covered, {"missing": expected, "covered": sorted(covered), "findings": findings}


def main() -> None:
    test_judge_merges_specific_canonical_rules_without_losing_business_rule()
    test_bound_rule_supplement_filters_generic_anchor_only_rule()
    test_tool_observation_canonical_mapping_preserves_expected_rule_ids()
    test_java_static_rules_cover_rare_business_patterns()
    print(json.dumps({"ok": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
