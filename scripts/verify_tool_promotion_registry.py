from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "mr-backend" / "worker"
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from orchestration.nodes import judge_findings
from rules.registry import external_tool_rule_map, promotable_rule_ids, tool_coverage_fill_rule_ids


def main() -> None:
    judge_source = (WORKER_DIR / "orchestration" / "nodes" / "judge_findings.py").read_text("utf-8")
    forbidden_literal_sets = [
        r"PROMOTABLE_TOOL_RULES\s*=\s*\{",
        r"TOOL_COVERAGE_FILL_RULES\s*=\s*\{",
        r"PROMOTABLE_EXTERNAL_TOOL_RULES\s*=\s*\{",
    ]
    for pattern in forbidden_literal_sets:
        assert not re.search(pattern, judge_source), f"tool promotion rule sets must come from registry, found {pattern}"

    promotable = promotable_rule_ids()
    fill_rules = tool_coverage_fill_rule_ids()
    external_map = external_tool_rule_map()
    required_rules = {
        "BE-API-001",
        "CODE-RESOURCE-005",
        "DEP-CVE-001",
        "REDIS-CMD-003",
        "REDIS-TTL-002",
        "SEC-INJECT-003",
        "SEC-SECRET-004",
    }
    assert len(promotable) >= 30, f"expected >=30 promotable rules, got {len(promotable)}"
    assert required_rules <= promotable, f"missing required promotable rules: {sorted(required_rules - promotable)}"
    assert judge_findings.PROMOTABLE_TOOL_RULES == promotable
    assert judge_findings.TOOL_COVERAGE_FILL_RULES == fill_rules
    assert judge_findings.PROMOTABLE_EXTERNAL_TOOL_RULES == external_map
    assert external_map.get("AvoidCatchingGenericException") == "CODE-EXC-003"
    assert external_map.get("CloseResource") == "CODE-RESOURCE-005"

    strong_observation = {
        "tool_name": "java_web_static",
        "rule_id": "CODE-RESOURCE-005",
        "confidence": 0.91,
        "file_path": "src/main/java/com/acme/ExportService.java",
        "line_start": 42,
    }
    weak_observation = {**strong_observation, "confidence": 0.84}
    imprecise_observation = {**strong_observation}
    imprecise_observation.pop("line_start")
    external_observation = {
        "tool_name": "pmd",
        "rule_id": "CloseResource",
        "confidence": 0.76,
        "file_path": "src/main/java/com/acme/ExportService.java",
        "line_start": 42,
    }
    assert judge_findings._promotable_tool_observation(strong_observation)
    assert not judge_findings._promotable_tool_observation(weak_observation)
    assert not judge_findings._promotable_tool_observation(imprecise_observation)
    assert judge_findings._canonical_tool_rule_id(external_observation) == "CODE-RESOURCE-005"
    assert judge_findings._promotable_tool_observation(external_observation)

    print(
        json.dumps(
            {
                "ok": True,
                "verified": "tool_promotion_registry",
                "promotable_rule_count": len(promotable),
                "external_tool_rule_count": len(external_map),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
