from __future__ import annotations

import sys
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

from orchestration.nodes.judge_findings import _merge_finding_metadata  # noqa: E402


def test_deduped_controller_validation_candidate_preserves_be_api_rule() -> None:
    primary = {
        "agent_id": "coding_agent",
        "confidence": 0.9,
        "covered_rules": ["CODE-NULL-001", "DB-MAP-004"],
        "skipped_rules": [],
        "merged_agent_ids": ["coding_agent"],
    }
    duplicate = {
        "agent_id": "backend_agent",
        "confidence": 0.87,
        "covered_rules": ["BE-API-001"],
        "skipped_rules": [],
        "merged_agent_ids": ["backend_agent"],
        "file_path": "src/main/java/com/acme/payment/api/PaymentAdminController.java",
        "line_start": 22,
        "title": "接口 RequestBody 缺少 Bean Validation",
    }

    _merge_finding_metadata(primary, duplicate)

    assert "BE-API-001" in primary["covered_rules"]
    assert "CODE-NULL-001" in primary["covered_rules"]
    assert set(primary["merged_agent_ids"]) == {"coding_agent", "backend_agent"}


def test_bound_primary_merge_preserves_secondary_gold_rules() -> None:
    primary = {
        "agent_id": "coding_agent",
        "confidence": 0.99,
        "rule_id": "DB-MAP-004",
        "bound_rule_id": "DB-MAP-004",
        "review_batch_label": "bound_rule_batch:DB-SQL-001,DB-QUERY-002,DB-IDX-003,DB-MAP-004",
        "covered_rules": ["DB-MAP-004"],
        "skipped_rules": ["CODE-NULL-001"],
        "merged_agent_ids": ["coding_agent"],
        "file_path": "src/main/java/com/acme/payment/api/PaymentAdminController.java",
        "line_start": 23,
        "title": "Controller 返回裸 Map 承载业务数据",
    }
    duplicate = {
        "agent_id": "backend_agent",
        "confidence": 0.87,
        "covered_rules": ["BE-API-001", "CODE-NULL-001"],
        "skipped_rules": [],
        "merged_agent_ids": ["backend_agent"],
        "file_path": "src/main/java/com/acme/payment/api/PaymentAdminController.java",
        "line_start": 22,
        "title": "接口 RequestBody 缺少 Bean Validation",
    }

    _merge_finding_metadata(primary, duplicate)

    assert primary["rule_id"] == "DB-MAP-004"
    assert {"DB-MAP-004", "BE-API-001", "CODE-NULL-001"}.issubset(set(primary["covered_rules"]))
    assert "CODE-NULL-001" not in primary["skipped_rules"]


def test_bound_primary_merge_preserves_destructive_ddl_rule() -> None:
    primary = {
        "agent_id": "database_agent",
        "confidence": 0.93,
        "rule_id": "DB-ROLLBACK-010",
        "bound_rule_id": "DB-ROLLBACK-010",
        "review_batch_label": "bound_rule_batch:DB-COMPAT-009,DB-ROLLBACK-010",
        "covered_rules": ["DB-ROLLBACK-010"],
        "skipped_rules": [],
        "merged_agent_ids": ["database_agent"],
        "file_path": "src/main/resources/db/migration/V20260607__complex_payment.sql",
        "line_start": 2,
        "title": "删除列无备份和回滚方案",
    }
    duplicate = {
        "agent_id": "database_agent",
        "confidence": 0.93,
        "covered_rules": ["DB-DDL-001"],
        "skipped_rules": [],
        "file_path": "src/main/resources/db/migration/V20260607__complex_payment.sql",
        "line_start": 2,
        "title": "迁移脚本包含破坏性 DDL",
    }

    _merge_finding_metadata(primary, duplicate)

    assert {"DB-ROLLBACK-010", "DB-DDL-001"}.issubset(set(primary["covered_rules"]))


if __name__ == "__main__":
    test_deduped_controller_validation_candidate_preserves_be_api_rule()
    test_bound_primary_merge_preserves_secondary_gold_rules()
    test_bound_primary_merge_preserves_destructive_ddl_rule()
    print("judge dedupe rule merge tests passed")
