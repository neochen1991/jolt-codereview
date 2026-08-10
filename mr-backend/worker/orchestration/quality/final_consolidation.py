from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


CONTRACT_VERSION = "final_finding_consolidation_v1"
TEXT_LIMIT = 1200
EVIDENCE_LIMIT = 1600


@dataclass(frozen=True)
class ConsolidationFailure:
    reason: str
    detail: str = ""


def _bounded_text(value: Any, limit: int = TEXT_LIMIT) -> str:
    return str(value or "").strip()[:limit]


def compact_findings(
    findings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    compact: list[dict[str, Any]] = []
    lookup: dict[str, dict[str, Any]] = {}
    width = max(2, len(str(max(1, len(findings)))))
    for index, finding in enumerate(findings, start=1):
        request_id = f"f_{index:0{width}d}"
        lookup[request_id] = finding
        problem = _bounded_text(finding.get("problem_description"))
        compact.append(
            {
                "id": request_id,
                "file_path": _bounded_text(finding.get("file_path"), 500),
                "line_start": finding.get("line_start"),
                "line_end": finding.get("line_end"),
                "title": _bounded_text(finding.get("title"), 500),
                "root_cause": problem,
                "impact": problem,
                "recommendation": _bounded_text(finding.get("recommendation")),
                "covered_rules": [str(rule) for rule in (finding.get("covered_rules") or []) if str(rule).strip()][:16],
                "agent_id": _bounded_text(finding.get("agent_id"), 200),
                "evidence_excerpt": _bounded_text(finding.get("evidence"), EVIDENCE_LIMIT),
            }
        )
    return compact, lookup


def _json_object(content: str) -> dict[str, Any] | None:
    raw = str(content or "").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_consolidation_response(
    content: str,
    known_ids: set[str],
) -> tuple[list[dict[str, Any]], ConsolidationFailure | None]:
    parsed = _json_object(content)
    if parsed is None:
        return [], ConsolidationFailure("invalid_json")
    if parsed.get("version") != CONTRACT_VERSION:
        return [], ConsolidationFailure("invariant_violation", "unsupported contract version")
    groups = parsed.get("groups")
    if not isinstance(groups, list):
        return [], ConsolidationFailure("invariant_violation", "groups must be a list")

    validated: list[dict[str, Any]] = []
    used: set[str] = set()
    for raw_group in groups:
        if not isinstance(raw_group, dict):
            return [], ConsolidationFailure("invariant_violation", "group must be an object")
        members = raw_group.get("member_ids")
        reason = str(raw_group.get("reason") or "").strip()
        if not isinstance(members, list) or len(members) < 2 or not reason:
            return [], ConsolidationFailure("invariant_violation", "group requires at least two members and a reason")
        normalized = [str(member) for member in members]
        unknown = [member for member in normalized if member not in known_ids]
        if unknown:
            return [], ConsolidationFailure("unknown_member", ",".join(sorted(set(unknown))))
        if len(set(normalized)) != len(normalized) or used.intersection(normalized):
            return [], ConsolidationFailure("overlapping_groups")
        used.update(normalized)
        validated.append({"member_ids": normalized, "reason": reason[:1000]})
    return validated, None

