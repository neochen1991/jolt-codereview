from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable

from budget import BudgetTracker


def budget_for_effort(effort: str) -> dict[str, Any]:
    cost_by_effort = {
        "trivial": 0.05,
        "fast": 0.20,
        "light": 0.20,
        "standard": 1.00,
        "deep": 3.00,
    }
    calls_by_effort = {
        "trivial": 0,
        "fast": 12,
        "light": 12,
        "standard": 32,
        "deep": 48,
    }
    wall_seconds_by_effort = {
        "trivial": 30,
        "fast": 180,
        "light": 180,
        "standard": 900,
        "deep": 900,
    }
    return {
        "effort": effort,
        "max_input_tokens": 0 if effort == "trivial" else (400000 if effort == "deep" else 120000 if effort == "standard" else 30000),
        "max_output_tokens": 0 if effort == "trivial" else (16000 if effort == "deep" else 8000),
        "max_wall_seconds": wall_seconds_by_effort.get(effort, 180),
        "max_cost_usd": cost_by_effort.get(effort, 0.20),
        "max_llm_calls": calls_by_effort.get(effort, 8),
        "max_llm_calls_per_agent": 0 if effort == "trivial" else 2,
        "max_findings": 40,
        "on_exceed": "degrade",
    }


def make_choose_effort_node(
    *,
    conn: sqlite3.Connection,
    job: Any,
    mr: Any,
    run_id: str,
    choose_effort: Callable[[str, list[Any], int, bool], str],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def choose_effort_node(state: dict[str, Any]) -> dict[str, Any]:
        files = state["files"]
        effort = choose_effort(job["requested_effort_level"], files, int(mr["risk_score"]), bool(state["fetch_degraded"]))
        conn.execute(
            "UPDATE review_runs SET effort_level = ?, budget_json = ? WHERE id = ?",
            (effort, json.dumps(budget_for_effort(effort)), run_id),
        )
        conn.execute("UPDATE review_jobs SET status = 'pre_scanning', heartbeat_at = CURRENT_TIMESTAMP WHERE id = ?", (job["id"],))
        conn.execute("UPDATE merge_requests SET review_status = 'pre_scanning' WHERE id = ?", (job["merge_request_id"],))
        conn.commit()
        budget = budget_for_effort(effort)
        return {**state, "effort": effort, "budget": budget, "budget_tracker": BudgetTracker.from_budget(budget)}

    return choose_effort_node
