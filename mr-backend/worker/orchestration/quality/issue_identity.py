from __future__ import annotations

import hashlib
import re
from typing import Any

from orchestration.quality.diff_scope import canonical_review_path


SEVERITY_RANK = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}
CALL_STOP_WORDS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "return",
    "throw",
    "assert",
    "string",
    "list",
    "map",
    "set",
}


def _text_blob(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in ("title", "problem_description", "evidence", "recommendation", "tool_rule_id")
    ).lower()


def typed_root_cause(item: dict[str, Any]) -> str:
    text = _text_blob(item)
    if any(marker in text for marker in ("sql 注入", "sql拼接", "sql 字符串拼接", "sql字符串拼接", "sql injection")):
        return "SQL_INJECTION"
    if "sql" in text and any(marker in text for marker in ("拼接", "concat", "injection", "注入")):
        return "SQL_INJECTION"
    if any(marker in text for marker in ("缺少分页", "没有分页", "结果上限", "unbounded query", "pagination", "limit clause")):
        return "UNBOUNDED_QUERY"
    if any(marker in text for marker in ("鉴权", "权限验证", "权限校验", "授权判断", "授权校验", "authorization", "permission check", "access control")):
        return "MISSING_AUTHORIZATION"
    if any(marker in text for marker in ("幂等", "idempot")):
        return "MISSING_IDEMPOTENCY"
    if any(marker in text for marker in ("空指针", "null dereference", "nullpointer", "缺少 null", "null 保护")):
        return "NULL_DEREFERENCE"
    if any(marker in text for marker in ("敏感信息日志", "敏感数据日志", "sensitive logging", "secret in log")):
        return "SENSITIVE_DATA_LOGGING"
    if any(marker in text for marker in ("吞掉异常", "异常吞", "swallow", "failure is ignored")):
        return "SWALLOWED_EXCEPTION"
    if any(marker in text for marker in ("资源泄漏", "resource leak", "未关闭", "not closed")):
        return "RESOURCE_LEAK"
    if any(marker in text for marker in ("路径遍历", "path traversal", "zip slip")):
        return "PATH_TRAVERSAL"
    rules = sorted(str(rule).strip().upper() for rule in (item.get("covered_rules") or []) if str(rule).strip())
    return f"RULE:{rules[0]}" if rules else "GENERAL"


def _sink_signature(item: dict[str, Any]) -> str:
    explicit = str(item.get("sink_signature") or item.get("primary_symbol") or item.get("symbol") or "").strip()
    if explicit:
        return explicit.lower()
    evidence = str(item.get("evidence") or "")
    calls = [match.lower() for match in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", evidence)]
    meaningful = [call for call in calls if call not in CALL_STOP_WORDS and not call.startswith(("get", "set"))]
    return meaningful[-1] if meaningful else ""


def canonical_issue_components(item: dict[str, Any]) -> dict[str, Any]:
    file_path = canonical_review_path(str(item.get("file_path") or ""))
    try:
        line = int(item.get("line_start") or 0)
    except (TypeError, ValueError):
        line = 0
    root = typed_root_cause(item)
    sink = _sink_signature(item)
    return {
        "version": "issue_v2",
        "file_path": file_path,
        "causal_anchor": line,
        "root_cause": root,
        "sink_signature": sink,
    }


def canonical_issue_fingerprint(item: dict[str, Any]) -> str:
    components = canonical_issue_components(item)
    payload = "|".join(
        [
            components["version"],
            components["file_path"],
            str(components["causal_anchor"]),
            components["root_cause"],
            components["sink_signature"],
        ]
    )
    return "issue_v2_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _priority_key(item: dict[str, Any]) -> tuple[int, int, float, int, str, str]:
    tool_backed = int(bool(item.get("tool_name") or item.get("source_tool_observation") or "tool_promoted" in (item.get("verification_flags") or [])))
    return (
        tool_backed,
        SEVERITY_RANK.get(str(item.get("severity") or "").lower(), 0),
        float(item.get("confidence") or 0),
        len(str(item.get("evidence") or "")),
        str(item.get("agent_id") or ""),
        str(item.get("title") or ""),
    )


def _source_name(item: dict[str, Any]) -> str:
    return str(item.get("tool_name") or item.get("agent_id") or item.get("source_type") or "unknown")


def _merge_cluster(members: list[dict[str, Any]], fingerprint: str) -> dict[str, Any]:
    ordered = sorted((dict(item) for item in members), key=_priority_key, reverse=True)
    primary = ordered[0]
    agents = sorted({str(item.get("agent_id") or "") for item in ordered if item.get("agent_id")})
    rules = sorted({str(rule) for item in ordered for rule in (item.get("covered_rules") or []) if rule})
    skipped_rules = sorted({str(rule) for item in ordered for rule in (item.get("skipped_rules") or []) if rule and str(rule) not in rules})
    evidence_variants = sorted(
        {
            str(item.get("evidence") or item.get("problem_description") or "").strip()
            for item in ordered
            if str(item.get("evidence") or item.get("problem_description") or "").strip()
        }
    )
    member_hashes = sorted({str(item.get("dedupe_hash") or "") for item in ordered if item.get("dedupe_hash")})
    components = canonical_issue_components(primary)
    trace = dict(primary.get("quality_trace") or {}) if isinstance(primary.get("quality_trace"), dict) else {}
    trace["canonical_issue"] = {
        **components,
        "fingerprint": fingerprint,
        "merged_count": len(ordered),
        "sources": sorted({_source_name(item) for item in ordered}),
        "member_hashes": member_hashes,
        "evidence_variants": evidence_variants,
    }
    primary.update(
        {
            "dedupe_hash": fingerprint,
            "file_path": components["file_path"],
            "covered_rules": rules,
            "skipped_rules": skipped_rules,
            "merged_agent_ids": agents,
            "quality_trace": trace,
            "confidence": max(float(item.get("confidence") or 0) for item in ordered),
        }
    )
    return primary


def cluster_canonical_issues(findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in findings:
        fingerprint = canonical_issue_fingerprint(item)
        groups.setdefault(fingerprint, []).append(item)
    merged: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for fingerprint in sorted(groups):
        members = groups[fingerprint]
        primary_source = max(members, key=_priority_key)
        primary = _merge_cluster(members, fingerprint)
        merged.append(primary)
        primary_original_hash = str(primary_source.get("dedupe_hash") or "")
        for item in members:
            if item is primary_source:
                continue
            duplicates.append(
                {
                    **item,
                    "rejected_reasons": ["deduped_canonical_issue_v2", "deduped_lower_rank"],
                    "merged_into_dedupe_hash": fingerprint,
                    "primary_member_hash": primary_original_hash,
                }
            )
    merged.sort(key=lambda item: (_priority_key(item), str(item.get("dedupe_hash") or "")), reverse=True)
    duplicates.sort(key=lambda item: (str(item.get("merged_into_dedupe_hash") or ""), str(item.get("dedupe_hash") or "")))
    return merged, duplicates
