from __future__ import annotations

import sqlite3
from typing import Any

from tools.models import ToolObservation


def _compose_observation_message(finding: dict[str, Any]) -> str:
    base = str(finding.get("problem_description") or finding.get("title") or "tool observation").strip()
    evidence = str(finding.get("evidence") or "").strip()
    if not evidence or evidence in base:
        return base
    return f"{base}\nEvidence: {evidence[:1200]}"


def findings_to_observations(findings: list[dict[str, Any]]) -> list[ToolObservation]:
    observations: list[ToolObservation] = []
    for finding in findings:
        observations.append(
            ToolObservation(
                tool_name=str(finding.get("tool_name") or finding.get("agent_id") or "unknown_tool"),
                rule_id=str(finding.get("tool_rule_id") or finding.get("title") or "") or None,
                severity=str(finding.get("severity") or "medium"),
                confidence=float(finding.get("confidence") or 0.5),
                file_path=str(finding.get("file_path") or ""),
                line_start=finding.get("line_start"),
                line_end=finding.get("line_end"),
                message=_compose_observation_message(finding),
                raw_artifact_id=finding.get("raw_artifact_id"),
            )
        )
    return observations


def save_tool_observations(conn: sqlite3.Connection, review_run_id: str, observations: list[ToolObservation], new_id) -> None:
    for observation in observations:
        conn.execute(
            """
            INSERT INTO tool_observations (
              id, review_run_id, tool_name, rule_id, severity, confidence, file_path,
              line_start, line_end, message, raw_artifact_id, adopted_by_agent, adoption_state
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("tool_obs"),
                review_run_id,
                observation.tool_name,
                observation.rule_id,
                observation.severity,
                observation.confidence,
                observation.file_path,
                observation.line_start,
                observation.line_end,
                observation.message,
                observation.raw_artifact_id,
                observation.adopted_by_agent,
                observation.adoption_state,
            ),
        )


def load_tool_observations(conn: sqlite3.Connection, review_run_id: str, limit: int = 500) -> list[dict[str, Any]]:
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'tool_observations'"
    ).fetchone()
    if not table:
        return []
    rows = conn.execute(
        """
        SELECT *
        FROM tool_observations
        WHERE review_run_id = ?
        ORDER BY
          CASE tool_name
            WHEN 'tree_sitter_code_graph' THEN 0
            WHEN 'semgrep' THEN 1
            WHEN 'gitleaks' THEN 2
            WHEN 'trivy' THEN 3
            WHEN 'osv' THEN 4
            WHEN 'dependency-check' THEN 5
            WHEN 'java_web_static' THEN 6
            WHEN 'pmd' THEN 7
            WHEN 'spotbugs' THEN 8
            WHEN 'checkstyle' THEN 9
            ELSE 20
          END,
          CASE severity
            WHEN 'critical' THEN 0
            WHEN 'high' THEN 1
            WHEN 'medium' THEN 2
            ELSE 3
          END,
          confidence DESC,
          created_at
        LIMIT ?
        """,
        (review_run_id, limit),
    ).fetchall()
    return [
        ToolObservation(
            tool_name=row["tool_name"],
            rule_id=row["rule_id"],
            severity=row["severity"],
            confidence=float(row["confidence"]),
            file_path=row["file_path"],
            line_start=row["line_start"],
            line_end=row["line_end"],
            message=row["message"],
            raw_artifact_id=row["raw_artifact_id"],
            adopted_by_agent=row["adopted_by_agent"],
            adoption_state=row["adoption_state"],
        ).to_prompt_item()
        for row in rows
    ]
