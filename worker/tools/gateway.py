from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolDecision:
    allowed: bool
    reason: str
    max_calls: int = 0


class ToolGateway:
    def __init__(self, conn: sqlite3.Connection, project_id: str, project_config: dict[str, Any]):
        self.conn = conn
        self.project_id = project_id
        self.tool_policy = project_config.get("tool_policy") or {}

    def check(self, agent_key: str, tool_name: str) -> ToolDecision:
        project_decision = self._check_project_policy(tool_name)
        if not project_decision.allowed:
            return project_decision
        binding = self._binding(agent_key, tool_name)
        if binding is None:
            return ToolDecision(False, "missing_expert_tool_binding")
        if int(binding["enabled"]) != 1:
            return ToolDecision(False, "expert_tool_binding_disabled")
        return ToolDecision(True, "allowed", int(binding["max_calls"]))

    def _check_project_policy(self, tool_name: str) -> ToolDecision:
        disabled = set(self.tool_policy.get("disabled_tools") or [])
        if tool_name in disabled:
            return ToolDecision(False, "project_tool_policy_disabled")
        enabled_tools = self.tool_policy.get("enabled_tools")
        if isinstance(enabled_tools, list) and enabled_tools and tool_name not in enabled_tools:
            return ToolDecision(False, "project_tool_policy_not_enabled")
        return ToolDecision(True, "project_allowed")

    def _binding(self, agent_key: str, tool_name: str) -> sqlite3.Row | None:
        table = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'expert_tool_bindings'"
        ).fetchone()
        if not table:
            return None
        return self.conn.execute(
            """
            SELECT *
            FROM expert_tool_bindings
            WHERE project_id = ? AND agent_key = ? AND tool_name = ?
            """,
            (self.project_id, agent_key, tool_name),
        ).fetchone()
