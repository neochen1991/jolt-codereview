import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skill_debug import (
    apply_debug_execution_controls,
    apply_debug_snapshot,
    production_side_effects_allowed,
    redact_snapshot,
)
from context.context_planner import plan_context_units
from context.skill_requirements import collect_skill_context_requirements
from orchestration.judging.evidence_pack import build_evidence_pack
from types import SimpleNamespace


def test_debug_side_effect_policy_disables_production_mutations() -> None:
    assert production_side_effects_allowed({"execution_kind": "skill_debug_candidate"}) is False
    assert production_side_effects_allowed({"execution_kind": "skill_debug_baseline"}) is False


def test_production_side_effect_policy_keeps_production_mutations() -> None:
    assert production_side_effects_allowed({"execution_kind": "production_review"}) is True
    assert production_side_effects_allowed({}) is True


def _snapshot() -> dict:
    return {
        "skill": {
            "skill_key": "target-skill",
            "content": "target instructions",
            "checkpoint_manifest": {
                "ok": True,
                "checkpoints": [{"checkpoint_id": "DRAFT-001"}],
            },
        },
        "assets": [{"skill_key": "target-skill", "asset_path": "SKILL.md", "content": "target instructions"}],
        "agent": {"agent_id": "security_agent", "custom_skills": ["other-skill", "target-skill"], "skills": ["other-skill", "target-skill"]},
    }


def test_targeted_baseline_removes_only_target_skill() -> None:
    agents = apply_debug_snapshot([_snapshot()["agent"]], _snapshot(), "baseline")
    assert agents[0]["custom_skills"] == ["other-skill"]
    assert agents[0]["skills"] == ["other-skill"]
    assert agents[0]["skill_assets"] == []


def test_targeted_candidate_keeps_target_skill() -> None:
    current = {
        **_snapshot()["agent"],
        "skill_checkpoint_manifests": {
            "target-skill": {"checkpoints": [{"checkpoint_id": "ACTIVE-001"}]},
            "other-skill": {"checkpoints": [{"checkpoint_id": "OTHER-001"}]},
        },
    }
    agents = apply_debug_snapshot([current], _snapshot(), "candidate")
    assert agents[0]["custom_skills"] == ["other-skill", "target-skill"]
    assert agents[0]["skill_assets"][0]["skill_key"] == "target-skill"
    assert agents[0]["skill_checkpoint_manifests"]["target-skill"]["checkpoints"][0]["checkpoint_id"] == "DRAFT-001"
    assert agents[0]["skill_checkpoint_manifests"]["other-skill"]["checkpoints"][0]["checkpoint_id"] == "OTHER-001"


def test_targeted_baseline_removes_target_skill_manifest() -> None:
    current = {
        **_snapshot()["agent"],
        "skill_checkpoint_manifests": {
            "target-skill": {"checkpoints": [{"checkpoint_id": "ACTIVE-001"}]},
            "other-skill": {"checkpoints": [{"checkpoint_id": "OTHER-001"}]},
        },
    }
    agents = apply_debug_snapshot([current], _snapshot(), "baseline")
    assert "target-skill" not in agents[0]["skill_checkpoint_manifests"]
    assert "other-skill" in agents[0]["skill_checkpoint_manifests"]


def test_debug_snapshot_redacts_secret_fields() -> None:
    value = redact_snapshot({"api_key": "sk-secret", "nested": {"authorization": "Bearer secret", "model": "gpt-test"}})
    assert value["api_key"] == "<redacted>"
    assert value["nested"]["authorization"] == "<redacted>"
    assert value["nested"]["model"] == "gpt-test"


def test_debug_execution_controls_do_not_fork_review_pipeline() -> None:
    configured = apply_debug_execution_controls(
        {"llm": {"default_model": "replay-model"}},
        {"kind": "skill_debug", "snapshot_mode": "frozen", "trace_level": "full", "llm_replay": "replay"},
    )
    assert configured["llm"]["exchange_mode"] == "replay"
    assert configured["llm"]["allow_exact_replay_storage"] is True
    assert configured["_execution_controls"]["snapshot_mode"] == "frozen"


def test_debug_and_production_share_context_and_judge_contract() -> None:
    checkpoint = {
        "checkpoint_id": "DRAFT-001",
        "evidence_scope": "cross_file",
        "context_queries": ["callers"],
        "max_dependency_hops": 2,
    }
    production_agent = {
        "agent_id": "security_agent",
        "custom_skills": ["target-skill"],
        "skills": ["target-skill"],
        "skill_checkpoint_manifests": {"target-skill": {"checkpoints": [checkpoint]}},
    }
    snapshot = _snapshot()
    snapshot["skill"]["checkpoint_manifest"] = {"ok": True, "checkpoints": [checkpoint]}
    debug_agent = apply_debug_snapshot([production_agent], snapshot, "candidate")[0]
    production_requirements = collect_skill_context_requirements([production_agent])
    debug_requirements = collect_skill_context_requirements([debug_agent])
    changed = SimpleNamespace(filename="src/Auth.java", patch="@@ -40,1 +40,1 @@\n-old\n+update(request)\n")
    kwargs = {
        "files": [changed],
        "source_file_contents": {"src/Auth.java": "\n".join(f"line {index}" for index in range(1, 100))},
        "related_context": {},
    }
    production_plan = plan_context_units(
        **kwargs,
        skill_checkpoint_ids=list(production_requirements.checkpoint_ids),
        context_queries=list(production_requirements.context_queries),
        max_dependency_hops=production_requirements.max_dependency_hops,
    )
    debug_plan = plan_context_units(
        **kwargs,
        skill_checkpoint_ids=list(debug_requirements.checkpoint_ids),
        context_queries=list(debug_requirements.context_queries),
        max_dependency_hops=debug_requirements.max_dependency_hops,
    )
    assert [unit.context_hash for unit in production_plan.units] == [unit.context_hash for unit in debug_plan.units]
    assert production_requirements.checkpoint_ids == debug_requirements.checkpoint_ids
    candidate = {"file_path": "src/Auth.java", "line_start": 40, "evidence": "update(request)", "trigger_condition": "untrusted request reaches update", "context_hash": production_plan.units[0].context_hash}
    production_decision = build_evidence_pack(candidate, context_health={"status": "full"}).status
    debug_decision = build_evidence_pack(candidate, context_health={"status": "full"}).status
    assert production_decision == debug_decision


if __name__ == "__main__":
    test_debug_side_effect_policy_disables_production_mutations()
    test_production_side_effect_policy_keeps_production_mutations()
    test_targeted_baseline_removes_only_target_skill()
    test_targeted_candidate_keeps_target_skill()
    test_targeted_baseline_removes_target_skill_manifest()
    test_debug_snapshot_redacts_secret_fields()
    test_debug_execution_controls_do_not_fork_review_pipeline()
    test_debug_and_production_share_context_and_judge_contract()
