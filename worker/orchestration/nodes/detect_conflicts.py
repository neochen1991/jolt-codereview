from __future__ import annotations

from collections import defaultdict
import sqlite3
from typing import Any

HIGH_SEVERITIES = {"critical", "high"}


def _line_key(item: dict[str, Any]) -> tuple[str, int | None]:
    line = item.get("line_start")
    return (str(item.get("file_path") or ""), int(line) if isinstance(line, int) else None)


def detect_conflicts(findings: list[dict[str, Any]], tool_observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    by_location: dict[tuple[str, int | None], list[dict[str, Any]]] = defaultdict(list)
    no_issue_by_location: dict[tuple[str, int | None], list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        if finding.get("disposition") == "no_issue" or finding.get("no_issue") is True:
            no_issue_by_location[_line_key(finding)].append(finding)
        else:
            by_location[_line_key(finding)].append(finding)

    for location, items in by_location.items():
        severities = {str(item.get("severity") or "") for item in items}
        agents = {str(item.get("agent_id") or "") for item in items}
        if len(items) > 1 and len(severities) > 1:
            conflicts.append({
                "type": "severity_disagreement",
                "location": {"file_path": location[0], "line_start": location[1]},
                "finding_hashes": [str(item.get("dedupe_hash") or "") for item in items],
                "agents": sorted(agents),
                "severities": sorted(severities),
                "summary": "多个 Agent 在同一位置报告不同严重级别"
            })
        no_issue_items = no_issue_by_location.get(location) or []
        if no_issue_items:
            conflicts.append({
                "type": "issue_vs_no_issue",
                "location": {"file_path": location[0], "line_start": location[1]},
                "finding_hashes": [str(item.get("dedupe_hash") or "") for item in items],
                "agents": sorted(agents | {str(item.get("agent_id") or "") for item in no_issue_items}),
                "summary": "一个 Agent 报告问题，另一个 Agent 在同一位置标记无问题"
            })

    observation_locations = {_line_key(item) for item in tool_observations}
    for finding in findings:
        location = _line_key(finding)
        confidence = float(finding.get("confidence") or 0)
        if confidence < 0.75 and location in observation_locations:
            conflicts.append({
                "type": "tool_supported_low_confidence",
                "location": {"file_path": location[0], "line_start": location[1]},
                "finding_hashes": [str(finding.get("dedupe_hash") or "")],
                "agents": [str(finding.get("agent_id") or "")],
                "summary": "工具观察支持该问题，但 Agent 置信度偏低"
            })
        evidence = str(finding.get("evidence") or "").strip()
        if str(finding.get("severity") or "") in HIGH_SEVERITIES and len(evidence) < 24:
            conflicts.append({
                "type": "high_severity_weak_evidence",
                "location": {"file_path": location[0], "line_start": location[1]},
                "finding_hashes": [str(finding.get("dedupe_hash") or "")],
                "agents": [str(finding.get("agent_id") or "")],
                "summary": "高严重级别问题缺少足够直接证据"
            })

    return conflicts


def make_detect_conflicts_node(
    *,
    conn: sqlite3.Connection,
    recorder: Any,
    run_id: str,
    load_tool_observations: Any,
):
    def detect_conflicts_node(state: dict[str, Any]) -> dict[str, Any]:
        conflict_span = recorder.span("detect_conflicts", "verifier")
        tool_observations = state.get("tool_observations") or load_tool_observations(conn, run_id)
        conflicts = detect_conflicts(state["verified_findings"], tool_observations)
        recorder.event(
            conflict_span,
            "conflicts_detected",
            f"Conflict detector 发现 {len(conflicts)} 个需要定向辩论的冲突",
            {"conflicts": conflicts[:20], "tool_observation_count": len(tool_observations)},
        )
        recorder.finish(conflict_span)
        return {**state, "conflicts": conflicts}

    return detect_conflicts_node
