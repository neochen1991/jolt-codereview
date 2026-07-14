from __future__ import annotations

import math
import re
import hashlib
from typing import Any

from diff.slicer import extract_added_lines
from rules.registry import rule_for_tool_observation, signature_keys_for
from orchestration.judging.evidence_pack import build_evidence_pack


SEVERITY_DOWNGRADE = {"critical": "high", "high": "medium", "medium": "low", "low": "info", "info": "info"}


def line_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def line_bucket(value: Any, bucket_size: int = 5) -> int:
    line = line_value(value)
    return 0 if line <= 0 else (line - 1) // bucket_size


def covered_rules(finding: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for raw in finding.get("covered_rules") or []:
        value = str(raw or "").strip()
        if value and value not in result:
            result.append(value)
    for key in ("rule_id", "tool_rule_id"):
        value = str(finding.get(key) or "").strip()
        if value and value not in result:
            result.append(value)
    return result


def file_glob(file_path: str) -> str:
    parts = [part for part in str(file_path or "").replace("\\", "/").split("/") if part]
    if not parts:
        return "**/*"
    return f"{'/'.join(parts[:2])}/**"


def normalized_snippet(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:500]


def snippet_hash(value: str) -> str:
    return hashlib.sha1(normalized_snippet(value).encode("utf-8")).hexdigest()


def suppression_keys(finding: dict[str, Any]) -> list[tuple[str, str, str]]:
    snippet = normalized_snippet(
        str(finding.get("evidence") or finding.get("problem_description") or finding.get("title") or finding.get("file_path") or "")
    )
    if not snippet:
        return []
    glob = file_glob(str(finding.get("file_path") or ""))
    digest = snippet_hash(snippet)
    return [(rule, glob, digest) for rule in covered_rules(finding)]


def changed_line_index(files: list[Any]) -> dict[str, dict[int, str]]:
    result: dict[str, dict[int, str]] = {}
    for changed in files or []:
        if isinstance(changed, dict):
            filename = str(changed.get("filename") or "")
            patch = str(changed.get("patch") or "")
        else:
            filename = str(getattr(changed, "filename", "") or "")
            patch = str(getattr(changed, "patch", "") or "")
        if not filename:
            continue
        result[filename] = {int(line): text for line, text in extract_added_lines(patch) if line is not None}
    return result


def _source_window(line_index: dict[str, dict[int, str]], file_path: str, line_start: int, window: int = 20) -> str:
    lines = line_index.get(file_path) or {}
    if not lines or line_start <= 0:
        return ""
    start = max(1, line_start - window)
    end = line_start + window
    return "\n".join(lines[index] for index in range(start, end + 1) if index in lines)


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _evidence_fragments(value: str) -> list[str]:
    fragments: list[str] = []
    for raw in re.split(r"[\n\r]+|Evidence:", str(value or ""), flags=re.IGNORECASE):
        fragment = _compact_text(re.sub(r"^(line\s+\d+\s*:|合并证据：)", "", raw.strip(), flags=re.IGNORECASE))
        fragment = fragment.strip("`'\" ")
        if len(fragment) >= 8 and fragment not in fragments:
            fragments.append(fragment)
    return fragments


def _strong_tokens(value: str) -> set[str]:
    result: set[str] = set()
    for raw in re.findall(r"[A-Za-z0-9_.:-]+|[\u4e00-\u9fff]{2,}", str(value or "").lower()):
        for token in re.split(r"[:/<>\"'=,()\[\]{};\s]+", raw):
            token = token.strip("._-")
            if len(token) >= 4:
                result.add(token)
        token = raw.strip("._-")
        if len(token) >= 4:
            result.add(token)
    return result


def _has_specific_token_overlap(evidence: str, source_line: str) -> bool:
    evidence_tokens = _strong_tokens(evidence)
    source_tokens = _strong_tokens(source_line)
    overlap = evidence_tokens & source_tokens
    if len(overlap) >= 2:
        return True
    return any(len(token) >= 6 and re.search(r"\d", token) for token in overlap)


def _snippet_quote_score(finding: dict[str, Any], line_index: dict[str, dict[int, str]]) -> float:
    evidence = _compact_text(str(finding.get("evidence") or ""))
    if len(evidence) < 8:
        return 0.0
    source_window = _source_window(line_index, str(finding.get("file_path") or ""), line_value(finding.get("line_start")))
    source = _compact_text(source_window)
    if len(source) < 8:
        return 0.0
    if evidence in source or source in evidence:
        return 0.2
    source_lines = [_compact_text(line) for line in source_window.splitlines() if len(_compact_text(line)) >= 8]
    fragments = _evidence_fragments(evidence)
    for line in source_lines:
        if line in evidence or any(fragment in line or line in fragment for fragment in fragments):
            return 0.2
        if any(_has_specific_token_overlap(fragment, line) for fragment in fragments):
            return 0.15
    source_chunks = [chunk.strip() for chunk in re.split(r"[;{}]\s*|\n", source) if len(chunk.strip()) >= 30]
    if any(chunk in evidence for chunk in source_chunks):
        return 0.2
    evidence_chunks = [evidence[index : index + 40] for index in range(0, max(0, len(evidence) - 39), 20)]
    return 0.15 if any(chunk in source for chunk in evidence_chunks if len(chunk) >= 30) else 0.0


def _source_location_score(finding: dict[str, Any], line_index: dict[str, dict[int, str]]) -> float:
    file_path = str(finding.get("file_path") or "")
    start = line_value(finding.get("line_start"))
    end = line_value(finding.get("line_end")) or start
    if not file_path or start <= 0 or end <= 0:
        return 0.0
    lines = line_index.get(file_path) or {}
    if not lines:
        return 0.0
    span = max(1, end - start + 1)
    if span > 20:
        return 0.0
    if any(line_no in lines for line_no in range(start, end + 1)):
        return 0.25
    if any(start - 2 <= line_no <= end + 2 for line_no in lines):
        return 0.18
    return 0.0


def _tool_backing_score(finding: dict[str, Any], tool_observations: list[dict[str, Any]]) -> tuple[float, list[dict[str, Any]]]:
    file_path = str(finding.get("file_path") or "")
    line = line_value(finding.get("line_start"))
    finding_rules = set(covered_rules(finding))
    matches: list[dict[str, Any]] = []
    for observation in tool_observations or []:
        if str(observation.get("file_path") or "") != file_path:
            continue
        obs_line = line_value(observation.get("line_start") or observation.get("line"))
        if line > 0 and obs_line > 0 and abs(obs_line - line) > 5:
            continue
        registry_rule = rule_for_tool_observation(observation)
        registry_rule_id = str(registry_rule.get("id") or "") if registry_rule else ""
        obs_rule = str(observation.get("rule_id") or observation.get("tool_rule_id") or "")
        if finding_rules and registry_rule_id and registry_rule_id not in finding_rules:
            continue
        if not registry_rule_id and finding_rules and obs_rule not in finding_rules:
            continue
        matches.append({**observation, "promoted_rule": registry_rule_id or obs_rule})
    if not matches:
        return 0.0, []
    return min(0.3, 0.18 + 0.06 * math.log2(len(matches) + 1)), matches


def _line_precision_score(finding: dict[str, Any]) -> float:
    start = line_value(finding.get("line_start"))
    end = line_value(finding.get("line_end")) or start
    if start <= 0 or end <= 0:
        return 0.0
    span = max(1, end - start + 1)
    if span <= 3:
        return 0.1
    if span > 20:
        return 0.0
    return round(max(0.0, 0.1 * (1 - (span - 3) / 17)), 4)


def _rule_alignment_score(finding: dict[str, Any], source_observations: list[dict[str, Any]]) -> float:
    rules = set(covered_rules(finding))
    if not rules:
        return 0.0
    observed = {
        str(item.get("promoted_rule") or item.get("rule_id") or item.get("tool_rule_id") or "")
        for item in source_observations or []
    }
    return 0.1 if rules & observed else 0.0


def _symbol_alignment_score(finding: dict[str, Any], related_context: dict[str, Any]) -> float:
    file_path = str(finding.get("file_path") or "")
    start = line_value(finding.get("line_start"))
    end = line_value(finding.get("line_end")) or start
    if not file_path or start <= 0:
        return 0.0
    symbols = []
    for key in ("changed_symbols", "modified_symbols"):
        items = related_context.get(key) if isinstance(related_context, dict) else None
        if isinstance(items, list):
            symbols.extend(item for item in items if isinstance(item, dict))
    for symbol in symbols:
        symbol_file = str(symbol.get("file_path") or symbol.get("definition_file") or symbol.get("file") or symbol.get("path") or "")
        if symbol_file and symbol_file != file_path:
            continue
        symbol_line = line_value(symbol.get("line_start") or symbol.get("definition_line") or symbol.get("start_line") or symbol.get("line"))
        if symbol_line and start - 2 <= symbol_line <= end + 2:
            return 0.15
    return 0.0


def signature(finding: dict[str, Any]) -> tuple[Any, ...]:
    rules = covered_rules(finding)
    primary_rule = rules[0] if rules else ""
    keys = signature_keys_for(primary_rule)
    values: list[Any] = []
    for key in keys:
        if key == "covered_rules":
            values.append(tuple(sorted(rules)))
        elif key == "line_bucket":
            values.append(line_bucket(finding.get("line_start")))
        elif key == "primary_symbol":
            values.append(str(finding.get("primary_symbol") or finding.get("symbol") or ""))
        else:
            values.append(str(finding.get(key) or ""))
    return tuple(values)


def _consensus_score(finding: dict[str, Any], peer_findings: list[dict[str, Any]]) -> tuple[float, list[str]]:
    own_signature = signature(finding)
    agents = {
        str(item.get("agent_id") or "")
        for item in peer_findings or []
        if signature(item) == own_signature and item.get("agent_id")
    }
    return (0.15, sorted(agents)) if len(agents) >= 2 else (0.0, sorted(agents))


def _suppression_penalty(finding: dict[str, Any], suppression_hints: list[dict[str, Any]]) -> tuple[float, dict[str, Any] | None]:
    if not suppression_hints:
        return 0.0, None
    keys = set(suppression_keys(finding))
    if not keys:
        return 0.0, None
    for hint in suppression_hints:
        key = (str(hint.get("rule_id") or ""), str(hint.get("file_glob") or ""), str(hint.get("snippet_hash") or ""))
        if key not in keys:
            continue
        try:
            count = max(1, int(hint.get("count") or 1))
        except (TypeError, ValueError):
            count = 1
        penalty = min(0.3, 0.1 * math.log(count + 1))
        return round(penalty, 4), {
            "rule_id": key[0],
            "file_glob": key[1],
            "snippet_hash": key[2],
            "count": count,
            "penalty": round(penalty, 4),
            "snippet_excerpt": str(hint.get("snippet_excerpt") or "")[:240],
        }
    return 0.0, None


def score(
    finding: dict[str, Any],
    *,
    files: list[Any] | None = None,
    line_index: dict[str, dict[int, str]] | None = None,
    related_context: dict[str, Any] | None = None,
    tool_observations: list[dict[str, Any]] | None = None,
    source_observations: list[dict[str, Any]] | None = None,
    peer_findings: list[dict[str, Any]] | None = None,
    suppression_hints: list[dict[str, Any]] | None = None,
    context_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    index = line_index if line_index is not None else changed_line_index(files or [])
    tool_score, matching_tools = _tool_backing_score(finding, tool_observations or [])
    consensus_score, consensus_agents = _consensus_score(finding, peer_findings or [finding])
    evidence_pack = build_evidence_pack(
        finding,
        semantic_paths=finding.get("semantic_paths") or [],
        tool_observations=source_observations or [],
        contradictions=finding.get("contradictions") or [],
        context_health=context_health or finding.get("context_health") or {},
    )
    components = {
        "tool_backing": round(tool_score, 4),
        "source_location": round(_source_location_score(finding, index), 4),
        "snippet_quote": round(_snippet_quote_score(finding, index), 4),
        "line_precision": round(_line_precision_score(finding), 4),
        "rule_alignment": round(_rule_alignment_score(finding, source_observations or []), 4),
        "symbol_alignment": round(_symbol_alignment_score(finding, related_context or {}), 4),
        "consensus": round(consensus_score, 4),
        "semantic_path_strength": round(evidence_pack.semantic_path_strength * 0.15, 4),
        "cross_file_evidence_path": round(0.1 if getattr(evidence_pack, "evidence_path", ()) else 0.0, 4),
        "trigger_specificity": round(evidence_pack.trigger_specificity * 0.1, 4),
        "context_completeness": round(evidence_pack.context_completeness * 0.1, 4),
    }
    suppression_penalty, matched_suppression_hint = _suppression_penalty(finding, suppression_hints or [])
    contradiction_penalty = round(evidence_pack.contradiction_penalty * 0.5, 4)
    total = round(max(0.0, min(1.0, sum(components.values())) - suppression_penalty - contradiction_penalty), 4)
    return {
        "version": "evidence_score_v2",
        "score": total,
        "components": components,
        "suppression_penalty": suppression_penalty,
        "contradiction_penalty": contradiction_penalty,
        "evidence_pack": evidence_pack.to_dict(),
        "matched_suppression_hint": matched_suppression_hint,
        "consensus_agents": consensus_agents,
        "matching_tool_count": len(matching_tools),
        "matching_tools": [
            {
                "tool_name": item.get("tool_name"),
                "rule_id": item.get("rule_id"),
                "promoted_rule": item.get("promoted_rule"),
                "file_path": item.get("file_path"),
                "line_start": item.get("line_start"),
            }
            for item in matching_tools[:5]
        ],
        "signature": list(signature(finding)),
    }


def apply_evidence_score_policy(finding: dict[str, Any], evidence_score: dict[str, Any], thresholds: dict[str, Any] | None = None) -> dict[str, Any]:
    result = dict(finding)
    score_value = float(evidence_score.get("score") or 0)
    drop_below = float((thresholds or {}).get("drop_below", 0.35))
    downgrade_below = float((thresholds or {}).get("downgrade_below", 0.5))
    pack = evidence_score.get("evidence_pack") if isinstance(evidence_score.get("evidence_pack"), dict) else {}
    pack_status = str(pack.get("status") or "")
    if pack_status == "rejected_with_reason":
        result["selected"] = 0
        reason_codes = [str(code) for code in pack.get("reason_codes") or [] if str(code)]
        result["judge_adjustment"] = reason_codes[0] if reason_codes else "contradicting_evidence"
        result["rejected_reasons"] = list(dict.fromkeys([*(result.get("rejected_reasons") or []), *reason_codes]))
    elif pack_status == "unresolved_context":
        result["selected"] = 0
        result["judge_adjustment"] = "unresolved_context"
    elif score_value < drop_below:
        result["selected"] = 0
        result["judge_adjustment"] = "evidence_score_below_drop_threshold"
    elif score_value < downgrade_below:
        result["severity"] = SEVERITY_DOWNGRADE.get(str(result.get("severity") or "medium"), "low")
        result["confidence"] = round(max(0.0, float(result.get("confidence") or 0) * 0.85), 4)
        result["judge_adjustment"] = "evidence_score_downgraded"
    result["evidence_score"] = evidence_score
    result["evidence_pack"] = pack
    return result
