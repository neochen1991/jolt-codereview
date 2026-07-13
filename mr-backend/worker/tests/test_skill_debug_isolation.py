import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skill_debug import (
    apply_debug_snapshot,
    production_side_effects_allowed,
    redact_snapshot,
)


def test_debug_side_effect_policy_disables_production_mutations() -> None:
    assert production_side_effects_allowed({"execution_kind": "skill_debug_candidate"}) is False
    assert production_side_effects_allowed({"execution_kind": "skill_debug_baseline"}) is False


def test_production_side_effect_policy_keeps_production_mutations() -> None:
    assert production_side_effects_allowed({"execution_kind": "production_review"}) is True
    assert production_side_effects_allowed({}) is True


def _snapshot() -> dict:
    return {
        "skill": {"skill_key": "target-skill", "content": "target instructions"},
        "assets": [{"skill_key": "target-skill", "asset_path": "SKILL.md", "content": "target instructions"}],
        "agent": {"agent_id": "security_agent", "custom_skills": ["other-skill", "target-skill"], "skills": ["other-skill", "target-skill"]},
    }


def test_targeted_baseline_removes_only_target_skill() -> None:
    agents = apply_debug_snapshot([_snapshot()["agent"]], _snapshot(), "baseline")
    assert agents[0]["custom_skills"] == ["other-skill"]
    assert agents[0]["skills"] == ["other-skill"]
    assert agents[0]["skill_assets"] == []


def test_targeted_candidate_keeps_target_skill() -> None:
    agents = apply_debug_snapshot([_snapshot()["agent"]], _snapshot(), "candidate")
    assert agents[0]["custom_skills"] == ["other-skill", "target-skill"]
    assert agents[0]["skill_assets"][0]["skill_key"] == "target-skill"


def test_debug_snapshot_redacts_secret_fields() -> None:
    value = redact_snapshot({"api_key": "sk-secret", "nested": {"authorization": "Bearer secret", "model": "gpt-test"}})
    assert value["api_key"] == "<redacted>"
    assert value["nested"]["authorization"] == "<redacted>"
    assert value["nested"]["model"] == "gpt-test"


if __name__ == "__main__":
    test_debug_side_effect_policy_disables_production_mutations()
    test_production_side_effect_policy_keeps_production_mutations()
    test_targeted_baseline_removes_only_target_skill()
    test_targeted_candidate_keeps_target_skill()
    test_debug_snapshot_redacts_secret_fields()
