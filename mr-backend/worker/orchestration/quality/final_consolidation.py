from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from orchestration.quality.issue_identity import canonical_issue_fingerprint


CONTRACT_VERSION = "final_finding_consolidation_v1"
TEXT_LIMIT = 1200
EVIDENCE_LIMIT = 1600
MERGED_EVIDENCE_LIMIT = 12000
SEVERITY_RANK = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}


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


def _priority_key(finding: dict[str, Any]) -> tuple[int, int, float, int, str]:
    flags = {str(flag) for flag in (finding.get("verification_flags") or [])}
    tool_backed = int(bool(finding.get("tool_name") or finding.get("source_tool_observation") or "tool_promoted" in flags))
    return (
        tool_backed,
        SEVERITY_RANK.get(str(finding.get("severity") or "").lower(), 0),
        float(finding.get("confidence") or 0),
        len(str(finding.get("evidence") or "")),
        str(finding.get("dedupe_hash") or ""),
    )


def _unique_scalars(values: list[Any]) -> list[str]:
    return sorted({str(value) for value in values if str(value).strip()})


def _unique_dicts(values: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        key = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(value))
    return result


def _merge_evidence(members: list[dict[str, Any]], primary: dict[str, Any]) -> str:
    variants: list[str] = []
    for member in [primary, *members]:
        evidence = str(member.get("evidence") or "").strip()
        if evidence and evidence not in variants:
            variants.append(evidence)
    return "\n\n合并证据：".join(variants)[:MERGED_EVIDENCE_LIMIT]


def _related_locations(members: list[dict[str, Any]], primary: dict[str, Any]) -> list[dict[str, Any]]:
    primary_location = (
        str(primary.get("file_path") or ""),
        primary.get("line_start"),
        primary.get("line_end"),
    )
    values: list[dict[str, Any]] = []
    for member in members:
        candidates = [
            {
                "file_path": str(member.get("file_path") or ""),
                "line_start": member.get("line_start"),
                "line_end": member.get("line_end"),
            },
            *(member.get("related_locations") or []),
        ]
        for location in candidates:
            if not isinstance(location, dict):
                continue
            key = (
                str(location.get("file_path") or ""),
                location.get("line_start"),
                location.get("line_end"),
            )
            if not key[0] or key == primary_location or location in values:
                continue
            values.append(
                {
                    "file_path": key[0],
                    "line_start": key[1],
                    "line_end": key[2],
                }
            )
    return values


def _merge_group(
    members: list[dict[str, Any]],
    *,
    reason: str,
    model_metadata: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    primary_source = max(members, key=_priority_key)
    primary = dict(primary_source)
    member_hashes = sorted({str(member.get("dedupe_hash") or "") for member in members if member.get("dedupe_hash")})
    covered_rules = _unique_scalars([rule for member in members for rule in (member.get("covered_rules") or [])])
    skipped_rules = [
        rule
        for rule in _unique_scalars([rule for member in members for rule in (member.get("skipped_rules") or [])])
        if rule not in covered_rules
    ]
    merged_agents = _unique_scalars(
        [
            value
            for member in members
            for value in [member.get("agent_id"), *(member.get("merged_agent_ids") or [])]
        ]
    )
    primary.update(
        {
            "severity": max(
                (str(member.get("severity") or "info").lower() for member in members),
                key=lambda value: SEVERITY_RANK.get(value, 0),
            ),
            "confidence": max(float(member.get("confidence") or 0) for member in members),
            "covered_rules": covered_rules,
            "skipped_rules": skipped_rules,
            "merged_agent_ids": merged_agents,
            "related_locations": _related_locations(members, primary_source),
            "evidence": _merge_evidence(members, primary_source),
            "source_observations": _unique_dicts(
                [value for member in members for value in (member.get("source_observations") or [])]
            ),
            "tool_provenance": _unique_dicts(
                [value for member in members for value in (member.get("tool_provenance") or [])]
            ),
        }
    )
    primary["dedupe_hash"] = canonical_issue_fingerprint(primary)
    trace = dict(primary_source.get("quality_trace") or {}) if isinstance(primary_source.get("quality_trace"), dict) else {}
    trace["final_consolidation"] = {
        "member_hashes": member_hashes,
        "primary_member_hash": str(primary_source.get("dedupe_hash") or ""),
        "reason": reason,
        "merged_count": len(members),
        **model_metadata,
    }
    primary["quality_trace"] = trace

    rejected = [
        {
            **member,
            "rejected_reasons": ["deduped_final_llm_consolidation"],
            "merged_into_dedupe_hash": primary["dedupe_hash"],
        }
        for member in members
        if member is not primary_source
    ]
    return primary, rejected


def merge_consolidation_groups(
    findings: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    *,
    model_metadata: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _, lookup = compact_findings(findings)
    grouped_ids = {str(member_id) for group in groups for member_id in (group.get("member_ids") or [])}
    merged: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for group in groups:
        members = [lookup[str(member_id)] for member_id in group.get("member_ids") or []]
        primary, group_rejected = _merge_group(
            members,
            reason=str(group.get("reason") or "")[:1000],
            model_metadata=dict(model_metadata or {}),
        )
        merged.append(primary)
        rejected.extend(group_rejected)
    for request_id, finding in lookup.items():
        if request_id not in grouped_ids:
            merged.append(dict(finding))
    if len(merged) > len(findings):
        raise ValueError("final consolidation increased finding count")
    return merged, rejected
