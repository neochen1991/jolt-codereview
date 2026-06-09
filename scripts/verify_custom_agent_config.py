from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from prompts.builder import build_prompt
from review_runtime import ChangedFile, ensure_worker_schema, load_agent_configs, route_agents


def main() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE agent_configs (
          id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL,
          agent_id TEXT NOT NULL,
          display_name TEXT NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1,
          applies_to_json TEXT NOT NULL DEFAULT '{}',
          tools_json TEXT NOT NULL DEFAULT '[]',
          skills_json TEXT NOT NULL DEFAULT '[]',
          rule_sets_json TEXT NOT NULL DEFAULT '[]',
          requires_deepagents INTEGER NOT NULL DEFAULT 0,
          min_confidence REAL NOT NULL DEFAULT 0.75,
          max_findings_per_mr INTEGER NOT NULL DEFAULT 12
        );
        CREATE TABLE expert_profiles (
          id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL,
          agent_key TEXT NOT NULL,
          display_name TEXT NOT NULL,
          role_profile TEXT NOT NULL,
          responsibility_scope TEXT NOT NULL,
          excluded_scope TEXT NOT NULL DEFAULT '',
          enabled INTEGER NOT NULL DEFAULT 1,
          min_confidence REAL NOT NULL DEFAULT 0.75,
          max_findings INTEGER NOT NULL DEFAULT 12,
          max_llm_calls INTEGER NOT NULL DEFAULT 6,
          max_tool_calls INTEGER NOT NULL DEFAULT 12,
          output_schema_version TEXT NOT NULL DEFAULT 'finding_v1'
        );
        """
    )
    ensure_worker_schema(conn)
    project_id = "project_custom_agent"
    custom_prompt = (
        "必须检查结算批次是否具备防重复入账、失败补偿和流水状态一致性；"
        "只输出能落到当前 MR diff 行的结算业务问题。"
    )
    conn.execute(
        """
        INSERT INTO expert_profiles (
          id, project_id, agent_key, display_name, role_profile, responsibility_scope,
          excluded_scope, enabled, min_confidence, max_findings, max_llm_calls, max_tool_calls
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0.75, 12, 6, 12)
        """,
        (
            "expert_settlement",
            project_id,
            "settlement_agent",
            "结算业务专家 Agent",
            "你是结算业务代码检视专家。",
            "只检视结算批次、入账、补偿、对账和状态一致性风险。",
            "不检视通用格式、安全漏洞、前端或依赖问题。",
        ),
    )
    conn.execute(
        """
        INSERT INTO agent_configs (
          id, project_id, agent_id, display_name, enabled, applies_to_json,
          tools_json, skills_json, rule_sets_json, requires_deepagents, min_confidence, max_findings_per_mr
        )
        VALUES (?, ?, ?, ?, 1, ?, ?, ?, '[]', 1, 0.75, 8)
        """,
        (
            "agent_settlement",
            project_id,
            "settlement_agent",
            "结算业务专家 Agent",
            json.dumps(
                {
                    "persona": "你是结算业务代码检视专家。",
                    "exclusive_scope": "settlement",
                    "review_scope": "只检视结算批次、入账、补偿、对账和状态一致性风险。",
                    "excluded_scope": "不检视通用格式、安全漏洞、前端或依赖问题。",
                    "custom_prompt": custom_prompt,
                    "languages": ["java"],
                    "paths": ["**/settlement/**", "**/accounting/**"],
                    "triggers": ["settlement", "ledger", "reconcile", "compensate"],
                },
                ensure_ascii=False,
            ),
            json.dumps(["static.heuristic_prescan"]),
            json.dumps(["settlement-business-review"]),
        ),
    )
    conn.commit()

    agents = load_agent_configs(conn, project_id)
    assert len(agents) == 1, agents
    agent = agents[0]
    assert agent["agent_id"] == "settlement_agent", agent
    assert agent["requires_deepagents"] is True, agent
    assert agent["applies_to"]["custom_prompt"] == custom_prompt, agent["applies_to"]

    files = [
        ChangedFile(
            filename="src/main/java/com/acme/settlement/SettlementService.java",
            status="modified",
            additions=12,
            deletions=0,
            changes=12,
            patch="@@ -0,0 +1,12 @@\n+class SettlementService {\n+  void settlementLedger() {}\n+}\n",
        )
    ]
    selected = route_agents(agents, files, "standard", {}, None, None, None)
    assert [item["agent_id"] for item in selected] == ["settlement_agent"], selected

    prompt, _ = build_prompt(agent, files, "## 结算规范\n- SETTLE-IDEMP-001 必须具备结算幂等键。")
    assert custom_prompt in prompt, prompt[:1000]
    assert "settlement_agent" in prompt, prompt[:1000]

    print(
        json.dumps(
            {
                "ok": True,
                "agent_id": agent["agent_id"],
                "selected_agents": [item["agent_id"] for item in selected],
                "requires_deepagents": agent["requires_deepagents"],
                "prompt_contains_custom_agent_prompt": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
