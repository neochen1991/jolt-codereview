from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from review_runtime import ChangedFile, ensure_worker_schema, load_agent_configs, load_skill_summary


def main() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE agent_configs (id TEXT PRIMARY KEY, project_id TEXT, agent_id TEXT, enabled INTEGER)")
    ensure_worker_schema(conn)

    project_id = "project_zero_code"
    conn.execute(
        """
        INSERT INTO custom_skills (
          id, project_id, skill_key, name, description, content, version, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
        """,
        (
            "skill_payment",
            project_id,
            "payment-business-review",
            "支付业务检视 Skill",
            "支付链路资金一致性和幂等风险检视",
            "\n".join(
                [
                    "## 角色增强",
                    "你熟悉支付、退款、撤销、补偿和对账链路。",
                    "",
                    "## 检视步骤",
                    "1. 检查金额状态流转是否具备幂等键。",
                    "2. 检查资金状态更新是否具备事务边界。",
                    "3. 每个问题必须输出精确行号和建议修改代码。",
                ]
            ),
            "v1",
        ),
    )
    conn.executemany(
        """
        INSERT INTO custom_skill_assets (
          id, project_id, skill_key, asset_path, asset_type, content, executable
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "asset_skill_md",
                project_id,
                "payment-business-review",
                "SKILL.md",
                "skill",
                "# 支付业务检视 Skill\n\n必须读取 references/payment-rules.md。",
                0,
            ),
            (
                "asset_reference",
                project_id,
                "payment-business-review",
                "references/payment-rules.md",
                "reference",
                "支付状态更新必须具备幂等键和事务边界。",
                0,
            ),
            (
                "asset_script",
                project_id,
                "payment-business-review",
                "scripts/check_payment_diff.py",
                "script",
                "print('check payment diff')",
                1,
            ),
        ],
    )
    conn.execute(
        """
        INSERT INTO expert_skill_bindings (
          id, project_id, agent_key, skill_key, priority, enabled
        )
        VALUES (?, ?, ?, ?, 100, 1)
        """,
        ("binding_payment_coding", project_id, "coding_agent", "payment-business-review"),
    )
    conn.commit()

    agents = load_agent_configs(conn, project_id)
    coding_agent = next(item for item in agents if item["agent_id"] == "coding_agent")
    assert "payment-business-review" in coding_agent["skills"], coding_agent["skills"]
    assert coding_agent["custom_skills"] == ["payment-business-review"], coding_agent.get("custom_skills")
    assert coding_agent["requires_deepagents"] is True, coding_agent.get("requires_deepagents")
    assert int(coding_agent["max_tool_calls"]) >= 6, coding_agent.get("max_tool_calls")
    asset_paths = {item["asset_path"] for item in coding_agent["skill_assets"]}
    assert "references/payment-rules.md" in asset_paths, asset_paths
    assert "scripts/check_payment_diff.py" in asset_paths, asset_paths

    files = [
        ChangedFile(
            filename="src/main/java/com/jolt/payment/PaymentService.java",
            status="modified",
            additions=8,
            deletions=0,
            changes=8,
            patch="@@ -0,0 +1,8 @@\n+class PaymentService {}\n",
        )
    ]
    summary = load_skill_summary("payment-business-review", files, conn, project_id)
    for expected in ["自定义检视 Skill", "支付业务检视 Skill", "资金一致性", "幂等键", "建议修改代码", "references/payment-rules.md", "scripts/check_payment_diff.py"]:
        assert expected in summary, expected

    deepagents_source = (ROOT / "worker" / "orchestration" / "deepagents_runner.py").read_text("utf-8")
    for expected in ["list_skill_assets", "read_skill_asset", "run_skill_script", "blocked_by_policy", "skill_asset_paths"]:
        assert expected in deepagents_source, expected

    print(
        json.dumps(
            {
                "ok": True,
                "agent_id": coding_agent["agent_id"],
                "skills": coding_agent["skills"],
                "skill_assets": sorted(asset_paths),
                "requires_deepagents": coding_agent["requires_deepagents"],
                "summary_contains_custom_skill": True,
                "deepagents_skill_tools": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
