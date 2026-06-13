from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable

from budget import BudgetTracker


def _numeric_override(raw: Any, fallback: int | float) -> int | float:
    if raw is None or raw == "":
        return fallback
    try:
        if isinstance(fallback, int) and not isinstance(fallback, bool):
            return max(0, int(raw))
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return fallback


def budget_for_effort(effort: str, budget_policy: dict[str, Any] | None = None) -> dict[str, Any]:
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
    budget = {
        "effort": effort,
        "max_input_tokens": 0 if effort == "trivial" else (400000 if effort == "deep" else 120000 if effort == "standard" else 30000),
        "max_output_tokens": 0 if effort == "trivial" else (16000 if effort == "deep" else 8000),
        "max_wall_seconds": wall_seconds_by_effort.get(effort, 180),
        "max_llm_calls": calls_by_effort.get(effort, 8),
        "max_llm_calls_per_agent": 0 if effort == "trivial" else 2,
        "max_findings": 40,
        "on_exceed": "degrade",
    }
    policy = budget_policy or {}
    effort_overrides = policy.get("efforts") if isinstance(policy.get("efforts"), dict) else {}
    override = effort_overrides.get(effort) if isinstance(effort_overrides.get(effort), dict) else {}
    for key in ("max_input_tokens", "max_output_tokens", "max_wall_seconds", "max_llm_calls", "max_llm_calls_per_agent", "max_findings"):
        if key in override:
            budget[key] = _numeric_override(override.get(key), budget[key])
    if override.get("on_exceed") in {"degrade", "fail"}:
        budget["on_exceed"] = override["on_exceed"]
    return budget


def make_choose_effort_node(
    *,
    conn: sqlite3.Connection,
    job: Any,
    mr: Any,
    run_id: str,
    choose_effort: Callable[[str, list[Any], int, bool], str],
    project_config: dict[str, Any] | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def choose_effort_node(state: dict[str, Any]) -> dict[str, Any]:
        files = state["files"]
        effort = choose_effort(job["requested_effort_level"], files, int(mr["risk_score"]), bool(state["fetch_degraded"]))
        budget = budget_for_effort(effort, (project_config or {}).get("budget_policy") or {})
        conn.execute(
            "UPDATE review_runs SET effort_level = ?, budget_json = ? WHERE id = ?",
            (effort, json.dumps(budget, ensure_ascii=False), run_id),
        )
        conn.execute("UPDATE review_jobs SET status = 'pre_scanning', heartbeat_at = CURRENT_TIMESTAMP WHERE id = ?", (job["id"],))
        conn.execute(
            "UPDATE merge_requests SET review_status = 'pre_scanning' WHERE id = ? AND review_status NOT IN ('merged', 'closed')",
            (job["merge_request_id"],),
        )
        conn.commit()
        return {**state, "effort": effort, "budget": budget, "budget_tracker": BudgetTracker.from_budget(budget)}

    return choose_effort_node
