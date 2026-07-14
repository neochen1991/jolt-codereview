from __future__ import annotations

import sys
import time
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

from budget import BudgetTracker  # noqa: E402
from orchestration.nodes.route_agents import make_route_agents_node  # noqa: E402


class _Recorder:
    def span(self, *_args):
        return "span"

    def event(self, *_args):
        return None

    def finish(self, *_args):
        return None

    def message(self, *_args):
        return None


def test_llm_budget_window_starts_after_prescan_when_routing_begins() -> None:
    stale_tracker = BudgetTracker(max_wall_seconds=1, max_llm_calls=2, started_at=time.monotonic() - 30)
    observed: dict[str, object] = {}

    def route_agents(_configs, _files, _effort, _project_config, _recorder, _span, tracker):
        observed["tracker"] = tracker
        observed["stopped"] = tracker.should_stop()
        return []

    node = make_route_agents_node(
        recorder=_Recorder(),
        project_config={},
        agent_configs=[],
        route_agents=route_agents,
    )
    result = node(
        {
            "files": [],
            "effort": "fast",
            "budget": {"max_wall_seconds": 1, "max_llm_calls": 2},
            "budget_tracker": stale_tracker,
            "tool_observations": [],
        }
    )

    assert observed["tracker"] is not stale_tracker
    assert observed["stopped"] is False
    assert result["budget_tracker"] is observed["tracker"]
    assert result["budget_tracker"].snapshot()["wall_seconds"] < 1


if __name__ == "__main__":
    test_llm_budget_window_starts_after_prescan_when_routing_begins()
    print("LLM budget window tests passed")
