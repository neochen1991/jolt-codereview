from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestration.skill_runtime_facts import build_skill_routing_facts, path_matches_applies_to, seal_skill_runtime_facts


AGENTS = [
    {
        "agent_id": "security_agent",
        "custom_skills": ["secure-review"],
        "skill_checkpoint_manifests": {
            "secure-review": {
                "compiler_version": "1.0.0",
                "skill_version": "v2",
                "bundle_sha256": "bundle",
                "source_hash": "source",
                "checkpoints": [
                    {"checkpoint_id": "SEC-001", "applies_to": "src/**/*.ts"},
                    {"checkpoint_id": "SEC-002", "applies_to": "src/**/*.ts"},
                ],
            }
        },
    }
]


def test_routing_facts_include_applicable_and_non_applicable_opportunities() -> None:
    applicable = build_skill_routing_facts(AGENTS, [AGENTS[0]], [{"path": "src/api/run.ts"}])
    assert applicable[0]["applicable"] is True, applicable
    assert applicable[0]["routed"] is True, applicable
    assert applicable[0]["matched_files"] == ["src/api/run.ts"], applicable

    not_applicable = build_skill_routing_facts(AGENTS, [], [{"path": "README.md"}])
    assert not_applicable[0]["applicable"] is False, not_applicable
    assert not_applicable[0]["routed"] is False, not_applicable

    assert path_matches_applies_to("src/Main.java", "Java 后端") is True


def test_runtime_facts_have_explicit_checkpoint_terminal_outcomes() -> None:
    routing = build_skill_routing_facts(AGENTS, [AGENTS[0]], [{"path": "src/api/run.ts"}])
    sealed = seal_skill_runtime_facts(
        routing,
        {
            "items": [
                {
                    "type": "skill_checkpoint",
                    "skill_key": "secure-review",
                    "checkpoint_id": "SEC-001",
                    "agent_id": "security_agent",
                    "checked": True,
                    "finding_count": 1,
                    "skipped": False,
                    "rejected_count": 0,
                },
                {
                    "type": "skill_checkpoint",
                    "skill_key": "secure-review",
                    "checkpoint_id": "SEC-002",
                    "agent_id": "security_agent",
                    "checked": False,
                    "finding_count": 0,
                    "skipped": False,
                    "rejected_count": 0,
                },
            ]
        },
        [{"covered_rules": ["SEC-001"], "agent_id": "security_agent"}],
        {("security_agent", "secure-review")},
        unclassified_deletions=1,
    )
    skill = sealed[0]
    assert skill["loaded"] is True, skill
    assert skill["required_checkpoint_count"] == 2, skill
    assert skill["completed_checkpoint_count"] == 1, skill
    assert skill["unresolved_checkpoint_count"] == 1, skill
    assert skill["judge_hit_checkpoint_count"] == 1, skill
    assert skill["judge_unclassified_deletion_count"] == 1, skill
    assert [item["outcome"] for item in skill["checkpoints"]] == ["hit", "unresolved"], skill


if __name__ == "__main__":
    test_routing_facts_include_applicable_and_non_applicable_opportunities()
    test_runtime_facts_have_explicit_checkpoint_terminal_outcomes()
    print({"ok": True, "verified": "skill_runtime_facts"})
