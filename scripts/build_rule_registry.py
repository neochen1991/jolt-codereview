from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "mr-backend" / "worker"
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from orchestration.nodes import judge_findings
from tools.tool_normalizer import CATEGORY_PRIMARY_RULE, RULE_CATEGORY_MAP


def agent_for_rule(rule_id: str) -> str:
    if rule_id in judge_findings.AGENT_BY_RULE:
        return judge_findings.AGENT_BY_RULE[rule_id]
    for prefix, agent_id in judge_findings.AGENT_BY_RULE_PREFIX.items():
        if rule_id.startswith(prefix):
            return agent_id
    return "coding_agent"


def severity_floor(rule_id: str) -> str:
    remediation = judge_findings.RULE_REMEDIATION.get(rule_id) or {}
    if isinstance(remediation, dict) and remediation.get("severity"):
        return str(remediation["severity"])
    if rule_id.startswith(("SEC-", "DEP-", "DB-DDL")):
        return "high"
    if rule_id.startswith("TEST-"):
        return "low"
    return "medium"


def main() -> None:
    rules: dict[str, dict] = {}
    for rule_id in sorted(
        set(judge_findings.PROMOTABLE_TOOL_RULES)
        | set(judge_findings.TOOL_COVERAGE_FILL_RULES)
        | set(judge_findings.RULE_REMEDIATION)
        | set(judge_findings.AGENT_BY_RULE)
        | set(CATEGORY_PRIMARY_RULE.values())
    ):
        if not rule_id:
            continue
        rules[rule_id] = {
            "id": rule_id,
            "severity_floor": severity_floor(rule_id),
            "agent_owners": [agent_for_rule(rule_id)],
            "category": next((category for category, primary in CATEGORY_PRIMARY_RULE.items() if primary == rule_id), rule_id),
            "evidence_requirements": {"requires_line": True, "min_evidence_components": 3},
            "tool_sources": [],
            "signature_keys": ["covered_rules", "file_path", "line_bucket", "primary_symbol"],
            "promote_from_tool": rule_id in judge_findings.PROMOTABLE_TOOL_RULES,
            "is_bound_document_rule": False,
        }

    for raw_rule, category in sorted(RULE_CATEGORY_MAP.items()):
        primary_rule = CATEGORY_PRIMARY_RULE.get(category)
        if not primary_rule or primary_rule not in rules:
            continue
        rules[primary_rule]["tool_sources"].append(
            {
                "tool": "*",
                "tool_rule_id": raw_rule,
                "min_confidence": 0.0,
            }
        )

    for raw_rule, target_rule in sorted(judge_findings.PROMOTABLE_EXTERNAL_TOOL_RULES.items()):
        if target_rule in rules:
            rules[target_rule]["tool_sources"].append(
                {
                    "tool": "*",
                    "tool_rule_id": raw_rule,
                    "min_confidence": 0.0,
                }
            )

    for rule in rules.values():
        seen = set()
        deduped = []
        for source in rule["tool_sources"]:
            key = (source["tool"], source["tool_rule_id"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(source)
        rule["tool_sources"] = deduped

    registry = {
        "generated_from": [
            "mr-backend/worker/orchestration/nodes/judge_findings.py",
            "mr-backend/worker/tools/tool_normalizer.py",
        ],
        "defaults": {
            "evidence_thresholds": {"drop_below": 0.35, "downgrade_below": 0.5},
            "signature_keys": ["covered_rules", "file_path", "line_bucket", "primary_symbol"],
        },
        "rules": [rules[key] for key in sorted(rules)],
    }
    output = ROOT / "mr-backend" / "worker" / "rules" / "registry.json"
    output.write_text(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "utf-8")
    print(json.dumps({"generated": str(output), "rule_count": len(rules)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
