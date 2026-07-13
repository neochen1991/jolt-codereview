import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestration.nodes.route_agents import apply_skill_debug_routing


def test_production_route_does_not_change_selection() -> None:
    agents = [{"agent_id": "coding_agent"}, {"agent_id": "security_agent"}]
    selected = [agents[0]]
    result, overridden = apply_skill_debug_routing(selected, agents, {"kind": "skill_debug", "mode": "production_route", "agent_key": "security_agent"})
    assert result == selected
    assert overridden is False


def test_targeted_adds_only_target_agent() -> None:
    agents = [{"agent_id": "coding_agent"}, {"agent_id": "security_agent"}, {"agent_id": "test_agent"}]
    result, overridden = apply_skill_debug_routing([agents[0]], agents, {"kind": "skill_debug", "mode": "targeted", "agent_key": "security_agent"})
    assert [item["agent_id"] for item in result] == ["coding_agent", "security_agent"]
    assert overridden is True


if __name__ == "__main__":
    test_production_route_does_not_change_selection()
    test_targeted_adds_only_target_agent()
