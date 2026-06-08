from __future__ import annotations

import sqlite3
import re
from collections import Counter
from typing import Any

from tools.tool_normalizer import normalized_rule_category


def _line_value(finding: dict[str, Any]) -> int:
    raw = finding.get("line_start") or finding.get("line_number") or finding.get("line")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _token_jaccard(a: str, b: str) -> float:
    left = set(re.findall(r"\w+", a.lower()))
    right = set(re.findall(r"\w+", b.lower()))
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _evidence_matches_source(evidence: str, source_snippet: str) -> dict[str, Any]:
    evidence_text = str(evidence or "").strip()
    source_text = str(source_snippet or "").strip()
    if not evidence_text or not source_text:
        return {"matched": False, "score": 0.0}
    evidence_lower = evidence_text.lower()
    source_lower = source_text.lower()
    containment_score = 0.0
    if evidence_lower in source_lower or source_lower in evidence_lower:
        containment_score = 1.0
    score = max(_token_jaccard(evidence_text, source_text), containment_score)
    return {"matched": score >= 0.5, "score": round(score, 4)}


def _with_flag(finding: dict[str, Any], flag: str) -> dict[str, Any]:
    flags = list(finding.get("verification_flags") or [])
    if flag not in flags:
        flags.append(flag)
    return {**finding, "verification_flags": flags}


def _rule_ids_for(finding: dict[str, Any]) -> list[str]:
    raw_values: list[Any] = [
        finding.get("rule_id"),
        finding.get("tool_rule_id"),
        finding.get("normalized_rule_category"),
    ]
    raw_values.extend(finding.get("covered_rules") or [])
    result: list[str] = []
    for raw in raw_values:
        value = str(raw or "").strip()
        if value and value not in result:
            result.append(value)
    return result


def _platform_rule_ids_for(finding: dict[str, Any]) -> list[str]:
    raw_values: list[Any] = [finding.get("rule_id"), finding.get("normalized_rule_category")]
    raw_values.extend(finding.get("covered_rules") or [])
    result: list[str] = []
    for raw in raw_values:
        value = str(raw or "").strip()
        if value and value not in result:
            result.append(value)
    return result


def _requires_source_evidence(finding: dict[str, Any]) -> bool:
    category = str(finding.get("normalized_rule_category") or "")
    rule_ids = set(_rule_ids_for(finding))
    mr_level_categories = {"MISSING_TEST_COVERAGE"}
    mr_level_rules = {"TEST-COVER-001", "JOLT_JAVA_MISSING_TEST"}
    return category not in mr_level_categories and not (rule_ids & mr_level_rules)


def _has_tool_observation_support(
    finding: dict[str, Any],
    tool_observations: list[dict[str, Any]],
    *,
    line_tolerance: int,
) -> bool:
    file_path = str(finding.get("file_path") or "")
    line_no = _line_value(finding)
    finding_rules = set(_rule_ids_for(finding))
    finding_categories = {normalized_rule_category(rule, finding.get("title")) for rule in finding_rules}
    for observation in tool_observations:
        if str(observation.get("file_path") or "") != file_path:
            continue
        obs_line = _line_value(observation)
        same_line = line_no <= 0 or obs_line <= 0 or abs(obs_line - line_no) <= line_tolerance
        obs_rule = str(observation.get("rule_id") or "")
        same_rule = obs_rule in finding_rules or normalized_rule_category(obs_rule, observation.get("message")) in finding_categories
        if same_line and same_rule:
            return True
    return False


def verify_candidate_findings(
    findings: list[dict[str, Any]],
    valid_files: set[str],
    agent_config_by_id: dict[str, dict[str, Any]],
    suppressed_hashes: set[str],
    diff_hunks: dict[str, list[tuple[int, int]]] | None = None,
    rule_registry: set[str] | None = None,
    source_snippet_loader: Any | None = None,
    tool_observations: list[dict[str, Any]] | None = None,
    line_tolerance: int = 3,
    min_evidence_jaccard: float = 0.5,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    diff_hunks = diff_hunks or {}
    rule_registry = rule_registry or set()
    tool_observations = tool_observations or []

    for finding in findings:
        reasons: list[str] = []
        file_path = str(finding.get("file_path") or "")
        if file_path not in valid_files:
            reasons.append("file_not_found")
        line_no = _line_value(finding)
        if file_path in valid_files and line_no > 0 and diff_hunks:
            hunks = diff_hunks.get(file_path, [])
            if hunks and not any(start - line_tolerance <= line_no <= end + line_tolerance for start, end in hunks):
                reasons.append("line_out_of_diff")
        evidence = str(finding.get("evidence") or "").strip()
        if (
            file_path in valid_files
            and evidence
            and line_no > 0
            and source_snippet_loader is not None
            and _requires_source_evidence(finding)
            and not _has_tool_observation_support(finding, tool_observations, line_tolerance=line_tolerance)
        ):
            evidence_signal = "\n".join(
                str(part or "").strip()
                for part in (evidence, finding.get("title"), finding.get("problem_description"))
                if str(part or "").strip()
            )
            evidence_match = _evidence_matches_source(evidence_signal, source_snippet_loader(file_path, line_no, window=5))
            evidence_score = float(evidence_match["score"])
            if evidence_score <= 0.0:
                reasons.append("evidence_not_in_source")
            elif evidence_score < min_evidence_jaccard:
                penalty = 0.05 if evidence_score >= 0.2 else 0.08
                finding = {
                    **_with_flag(finding, "low_evidence_match"),
                    "confidence": max(0.0, float(finding.get("confidence") or 0) - penalty),
                    "evidence_match_score": evidence_score,
                }
        rule_ids = _platform_rule_ids_for(finding)
        if rule_registry and rule_ids and not any(rule_id in rule_registry for rule_id in rule_ids):
            finding = _with_flag(finding, "unknown_rule")
        confidence = float(finding.get("confidence") or 0)
        config = agent_config_by_id.get(str(finding.get("agent_id") or ""), {})
        verification_flags = set(finding.get("verification_flags") or [])
        if confidence < float(config.get("min_confidence", 0.7)) and "low_evidence_match" not in verification_flags:
            reasons.append("below_confidence")
        if finding.get("dedupe_hash") in suppressed_hashes:
            reasons.append("suppressed_by_feedback")
        if not finding.get("title") or not finding.get("problem_description"):
            reasons.append("schema_invalid")
        if reasons:
            rejected.append({**finding, "rejected_reasons": reasons})
            continue
        accepted.append(finding)

    return accepted, rejected


def rejected_reason_counts(rejected: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for item in rejected:
        counter.update(str(reason) for reason in item.get("rejected_reasons") or [])
    return dict(counter)


def make_verify_findings_node(
    *,
    conn: sqlite3.Connection,
    recorder: Any,
    job: Any,
    project_id: str,
    run_id: str,
    agent_config_by_id: dict[str, dict[str, Any]],
    load_feedback_suppressions: Any,
    load_feedback_boosts: Any,
    verify_findings: Any,
    load_tool_observations: Any,
):
    def verify_findings_node(state: dict[str, Any]) -> dict[str, Any]:
        files = state["files"]
        all_findings = state["all_findings"]
        conn.execute("UPDATE review_jobs SET status = 'judging', heartbeat_at = CURRENT_TIMESTAMP WHERE id = ?", (job["id"],))
        conn.execute("UPDATE merge_requests SET review_status = 'judging' WHERE id = ?", (job["merge_request_id"],))
        conn.commit()
        verifier_span = recorder.span("verify_findings", "verifier")
        suppressed_hashes = load_feedback_suppressions(conn, project_id)
        boosted_hashes = load_feedback_boosts(conn, project_id)
        tool_observations = state.get("tool_observations") or load_tool_observations(conn, run_id)
        verified_findings = verify_findings(
            recorder,
            verifier_span,
            all_findings,
            files,
            agent_config_by_id,
            suppressed_hashes,
            boosted_hashes,
            tool_observations,
            state.get("source_file_contents") or {},
        )
        recorder.event(
            verifier_span,
            "finding_verified",
            f"Verifier 接收 {len(all_findings)} 个候选，保留 {len(verified_findings)} 个",
            {
                "input": len(all_findings),
                "accepted": len(verified_findings),
                "tool_observation_count": len(tool_observations),
                "suppressed_feedback_count": len(suppressed_hashes),
                "boosted_feedback_count": len(boosted_hashes),
                "rejected_reason_counts": rejected_reason_counts(
                    [item for item in all_findings if item.get("rejected_reasons")]
                ),
            },
        )
        recorder.finish(verifier_span)
        return {**state, "verified_findings": verified_findings}

    return verify_findings_node
