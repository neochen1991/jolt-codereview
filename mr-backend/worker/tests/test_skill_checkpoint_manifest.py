from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
fake_deepagents_runner = types.ModuleType("orchestration.deepagents_runner")
fake_deepagents_runner.run_bounded_deepagent = lambda **_kwargs: {"tool_calls": [], "content": ""}
sys.modules.setdefault("orchestration.deepagents_runner", fake_deepagents_runner)

from orchestration.nodes.run_experts import _bound_rule_batches


def test_compiled_manifest_wins_over_runtime_markdown_parser() -> None:
    batches = _bound_rule_batches(
        {
            "agent_id": "security_agent",
            "custom_skills": ["secure-review"],
            "skill_assets": [
                {
                    "skill_key": "secure-review",
                    "asset_path": "SKILL.md",
                    "content": "## RUNTIME-001 不应被重新解析\n- check: runtime",
                }
            ],
            "skill_checkpoint_manifests": {
                "secure-review": {
                    "schema_version": "skill_checkpoint_manifest_v1",
                    "compiler_version": "1.0.0",
                    "source_hash": "bundle-hash",
                    "checkpoints": [
                        {
                            "skill_key": "secure-review",
                            "checkpoint_id": "COMPILED-001",
                            "rule_id": "COMPILED-001",
                            "title": "编译产物",
                            "check": "必须使用编译产物",
                            "required_evidence": "源码证据",
                            "false_positive_patterns": "固定输入",
                            "fix_guidance": "修复建议",
                            "source_path": "references/rules.md",
                            "parse_quality": "structured",
                        }
                    ],
                }
            },
            "bound_rules": [],
        }
    )
    assert [item["checkpoint_id"] for item in batches] == ["COMPILED-001"], batches
    checkpoint = batches[0]["agent"]["skill_checkpoints"][0]
    assert checkpoint["compiler_version"] == "1.0.0", checkpoint
    assert checkpoint["manifest_source_hash"] == "bundle-hash", checkpoint


def test_legacy_skill_without_manifest_still_uses_markdown_parser() -> None:
    batches = _bound_rule_batches(
        {
            "agent_id": "security_agent",
            "custom_skills": ["legacy-review"],
            "skill_assets": [
                {
                    "skill_key": "legacy-review",
                    "asset_path": "SKILL.md",
                    "content": """## LEGACY-001 旧规则
- check: 检查旧规则。
- required_evidence: 源码证据。
- false_positive_patterns: 固定输入。
- fix_guidance: 修复建议。
""",
                }
            ],
            "bound_rules": [],
        }
    )
    assert [item["checkpoint_id"] for item in batches] == ["LEGACY-001"], batches
    checkpoint = batches[0]["agent"]["skill_checkpoints"][0]
    assert checkpoint["parse_quality"] == "structured", checkpoint
    assert checkpoint.get("manifest_mode") == "legacy_fallback", checkpoint


if __name__ == "__main__":
    test_compiled_manifest_wins_over_runtime_markdown_parser()
    test_legacy_skill_without_manifest_still_uses_markdown_parser()
    print({"ok": True, "verified": "skill_checkpoint_manifest"})
