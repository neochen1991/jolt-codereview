from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

fake_deepagents_runner = types.ModuleType("orchestration.deepagents_runner")
fake_deepagents_runner.run_bounded_deepagent = lambda **_kwargs: {"tool_calls": [], "content": ""}
sys.modules.setdefault("orchestration.deepagents_runner", fake_deepagents_runner)

from orchestration.nodes.run_experts import _bound_rule_batches
from prompts.builder import build_prompt
from rules.skill_checkpoint_parser import parse_skill_checkpoints


SKILL_WITH_CHECKPOINTS = """# Security Skill

## SEC-CMD-001 命令注入检查
- severity: high
- applies_to: Java 后端

### 检查点
用户输入不能拼接进 Runtime.exec 或 ProcessBuilder。

### 证据要求
- 外部输入来源
- 命令执行 sink
- 缺少白名单或枚举映射

### 误报模式
- 固定常量命令
- 参数来自内部枚举

## SEC-PATH-002 路径穿越检查
- severity: medium

### 如何检查
请求参数参与文件读取时必须 normalize/canonical 并限制在基准目录内。
"""


def test_skill_markdown_is_parsed_into_auditable_checkpoints() -> None:
    checkpoints = parse_skill_checkpoints("secure-review-skill", SKILL_WITH_CHECKPOINTS)
    assert [item["checkpoint_id"] for item in checkpoints] == ["SEC-CMD-001", "SEC-PATH-002"], checkpoints
    first = checkpoints[0]
    assert first["skill_key"] == "secure-review-skill", first
    assert first["title"] == "命令注入检查", first
    assert first["severity"] == "high", first
    assert "Runtime.exec" in first["check"], first
    assert "命令执行 sink" in first["required_evidence"], first
    assert "固定常量命令" in first["false_positive_patterns"], first


def test_custom_skill_creates_skill_scoped_batch_without_free_review() -> None:
    batches = _bound_rule_batches(
        {
            "agent_id": "security_agent",
            "custom_skills": ["secure-review-skill"],
            "skill_assets": [
                {"skill_key": "secure-review-skill", "asset_path": "SKILL.md", "content": SKILL_WITH_CHECKPOINTS}
            ],
            "bound_rules": [],
        }
    )
    assert [batch["label"] for batch in batches] == [
        "bound_skill:secure-review-skill:SEC-CMD-001",
        "bound_skill:secure-review-skill:SEC-PATH-002",
    ], batches
    batch_agent = batches[0]["agent"]
    assert batch_agent["bound_skill_batch"]["skill_key"] == "secure-review-skill", batch_agent
    assert batch_agent["bound_skill_batch"]["checkpoint_id"] == "SEC-CMD-001", batch_agent
    assert batch_agent["bound_skill_batch"]["enforce_skill_scope"] is True, batch_agent
    assert batch_agent["custom_skills"] == ["secure-review-skill"], batch_agent
    assert batch_agent["skill_checkpoints"][0]["checkpoint_id"] == "SEC-CMD-001", batch_agent
    assert batch_agent["skill_assets"][0]["skill_key"] == "secure-review-skill", batch_agent


def test_skill_scoped_prompt_disables_expert_free_review() -> None:
    prompt, _safety = build_prompt(
        {
            "agent_id": "security_agent",
            "display_name": "Security Agent",
            "applies_to": {"persona": "安全专家", "exclusive_scope": "security", "review_scope": "安全问题"},
            "bound_skill_batch": {
                "skill_key": "secure-review-skill",
                "checkpoint_id": "SEC-CMD-001",
                "index": 1,
                "total": 1,
                "enforce_skill_scope": True,
            },
            "skill_checkpoints": [
                {
                    "skill_key": "secure-review-skill",
                    "checkpoint_id": "SEC-CMD-001",
                    "title": "命令注入检查",
                    "check": "用户输入不能拼接进 Runtime.exec 或 ProcessBuilder。",
                    "required_evidence": "外部输入来源；命令执行 sink；缺少白名单或枚举映射",
                    "false_positive_patterns": "固定常量命令；参数来自内部枚举",
                }
            ],
            "bound_rules": [],
            "tool_observations": [],
        },
        [
            SimpleNamespace(
                filename="src/App.java",
                status="modified",
                additions=1,
                deletions=0,
                patch="+Runtime.getRuntime().exec(cmd);",
            )
        ],
        "# SKILL.md\n\n只检查命令注入，不检查其他安全问题。",
    )
    assert "bound_skill_batch" in prompt, prompt
    assert "SEC-CMD-001" in prompt, prompt
    assert "skill_checkpoints" in prompt, prompt
    assert "只允许输出当前 bound_skill_batch.skill_key 对应 Skill 明确要求检查的问题" in prompt, prompt
    assert "当前 checkpoint" in prompt, prompt
    assert "禁止执行专家自由检视" in prompt, prompt


if __name__ == "__main__":
    test_skill_markdown_is_parsed_into_auditable_checkpoints()
    test_custom_skill_creates_skill_scoped_batch_without_free_review()
    test_skill_scoped_prompt_disables_expert_free_review()
