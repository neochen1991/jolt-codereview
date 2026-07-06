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


def test_custom_skill_creates_skill_scoped_batch_without_free_review() -> None:
    batches = _bound_rule_batches(
        {
            "agent_id": "security_agent",
            "custom_skills": ["secure-review-skill"],
            "skill_assets": [
                {"skill_key": "secure-review-skill", "asset_path": "SKILL.md", "content": "..."}
            ],
            "bound_rules": [],
        }
    )
    assert [batch["label"] for batch in batches] == ["bound_skill:secure-review-skill"], batches
    batch_agent = batches[0]["agent"]
    assert batch_agent["bound_skill_batch"]["skill_key"] == "secure-review-skill", batch_agent
    assert batch_agent["bound_skill_batch"]["enforce_skill_scope"] is True, batch_agent
    assert batch_agent["custom_skills"] == ["secure-review-skill"], batch_agent
    assert batch_agent["skill_assets"][0]["skill_key"] == "secure-review-skill", batch_agent


def test_skill_scoped_prompt_disables_expert_free_review() -> None:
    prompt, _safety = build_prompt(
        {
            "agent_id": "security_agent",
            "display_name": "Security Agent",
            "applies_to": {"persona": "安全专家", "exclusive_scope": "security", "review_scope": "安全问题"},
            "bound_skill_batch": {
                "skill_key": "secure-review-skill",
                "index": 1,
                "total": 1,
                "enforce_skill_scope": True,
            },
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
    assert "只允许输出当前 bound_skill_batch.skill_key 对应 Skill 明确要求检查的问题" in prompt, prompt
    assert "禁止执行专家自由检视" in prompt, prompt


if __name__ == "__main__":
    test_custom_skill_creates_skill_scoped_batch_without_free_review()
    test_skill_scoped_prompt_disables_expert_free_review()
