from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from orchestration.nodes.choose_effort import budget_for_effort  # noqa: E402


configured = {
    "efforts": {
        "standard": {
            "max_llm_calls": 88,
            "max_wall_seconds": 1800,
            "max_cost_usd": 6.5,
            "max_output_tokens": 20000,
            "max_findings": 80,
        },
        "deep": {
            "max_llm_calls": 144,
            "max_wall_seconds": 2700,
            "max_cost_usd": 12.0,
        },
    }
}

standard = budget_for_effort("standard", configured)
deep = budget_for_effort("deep", configured)
fast = budget_for_effort("fast", configured)

assert standard["max_llm_calls"] == 88, standard
assert standard["max_wall_seconds"] == 1800, standard
assert standard["max_cost_usd"] == 6.5, standard
assert standard["max_output_tokens"] == 20000, standard
assert standard["max_findings"] == 80, standard
assert deep["max_llm_calls"] == 144, deep
assert deep["max_wall_seconds"] == 2700, deep
assert deep["max_cost_usd"] == 12.0, deep
assert fast["max_llm_calls"] == 12, fast

print("budget policy override verified")
