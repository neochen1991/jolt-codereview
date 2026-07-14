from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


EvidenceStatus = Literal["confirmed", "needs_review", "rejected_with_reason", "unresolved_context"]


@dataclass(frozen=True)
class EvidencePack:
    version: str
    status: EvidenceStatus
    changed_location: dict[str, Any] = field(default_factory=dict)
    root_cause: str = ""
    impact: str = ""
    direct_evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    supporting_evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    semantic_paths: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    trigger_conditions: tuple[str, ...] = field(default_factory=tuple)
    contradictions: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    verifier_results: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    unresolved_context: tuple[str, ...] = field(default_factory=tuple)
    semantic_path_strength: float = 0.0
    trigger_specificity: float = 0.0
    contradiction_penalty: float = 0.0
    context_completeness: float = 0.0
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _semantic_strength(paths: list[dict[str, Any]]) -> float:
    if not paths:
        return 0.0
    confidence_score = {"typed": 1.0, "syntax": 0.8, "heuristic": 0.25}
    path_scores: list[float] = []
    for path in paths:
        edges = [edge for edge in path.get("edges") or [] if isinstance(edge, dict)]
        if not edges:
            continue
        weakest = min(confidence_score.get(str(edge.get("confidence") or "heuristic"), 0.0) for edge in edges)
        completeness = 1.0 if path.get("complete") is True else 0.8
        path_scores.append(weakest * completeness)
    return round(max(path_scores, default=0.0), 4)


def _trigger_specificity(finding: dict[str, Any]) -> tuple[float, tuple[str, ...]]:
    raw = finding.get("trigger_conditions") or finding.get("trigger_condition") or finding.get("preconditions") or []
    values = [str(item).strip() for item in raw] if isinstance(raw, list) else [str(raw).strip()]
    values = [value for value in values if value]
    if not values:
        return 0.0, ()
    strongest = max(len(value.split()) for value in values)
    score = 0.9 if strongest >= 6 else 0.7 if strongest >= 3 else 0.4
    return score, tuple(values)


def _context_completeness(finding: dict[str, Any], context_health: dict[str, Any]) -> float:
    status = str(context_health.get("status") or context_health.get("context_state") or "").lower()
    if status == "full":
        score = 1.0
    elif status == "partial":
        score = 0.6
    elif status == "patch_only":
        score = 0.2
    else:
        score = 0.5 if finding.get("context_hash") else 0.2
    unresolved = int(context_health.get("context_units_unresolved") or 0)
    if unresolved:
        score = min(score, 0.3)
    return round(score, 4)


def _contradiction_reason(item: dict[str, Any]) -> str:
    kind = str(item.get("kind") or "counter_evidence").strip().lower()
    aliases = {
        "authorization_guard": "contradicting_authorization_guard",
        "permission_guard": "contradicting_authorization_guard",
        "null_guard": "contradicting_null_guard",
        "transaction_compensation": "contradicting_transaction_compensation",
        "sanitization": "contradicting_sanitization",
    }
    return aliases.get(kind, f"contradicting_{kind}")


def build_evidence_pack(
    finding: dict[str, Any],
    *,
    semantic_paths: list[dict[str, Any]] | None = None,
    tool_observations: list[dict[str, Any]] | None = None,
    contradictions: list[dict[str, Any]] | None = None,
    context_health: dict[str, Any] | None = None,
) -> EvidencePack:
    paths = [item for item in (semantic_paths or finding.get("semantic_paths") or []) if isinstance(item, dict)]
    counter_evidence = [item for item in (contradictions or finding.get("contradictions") or []) if isinstance(item, dict)]
    health = context_health or finding.get("context_health") or {}
    semantic_strength = _semantic_strength(paths)
    trigger_score, triggers = _trigger_specificity(finding)
    context_score = _context_completeness(finding, health if isinstance(health, dict) else {})
    contradiction_penalty = round(min(1.0, 0.65 + 0.1 * max(0, len(counter_evidence) - 1)), 4) if counter_evidence else 0.0
    changed_location = {
        "file_path": finding.get("file_path"),
        "line_start": finding.get("line_start"),
        "line_end": finding.get("line_end"),
    } if finding.get("file_path") and finding.get("line_start") else {}
    root_cause = str(finding.get("root_cause") or finding.get("problem_description") or "").strip()
    impact = str(finding.get("impact") or finding.get("impact_description") or "").strip()
    unresolved_values = finding.get("unresolved_context") or []
    unresolved_context = tuple(
        str(item).strip()
        for item in (unresolved_values if isinstance(unresolved_values, list) else [unresolved_values])
        if str(item).strip()
    )
    direct: list[dict[str, Any]] = []
    if changed_location:
        direct.append({"kind": "changed_location", **changed_location})
    if finding.get("evidence"):
        direct.append({"kind": "source_excerpt", "text": str(finding.get("evidence"))[:1000]})
    for item in tool_observations or []:
        direct.append({"kind": "tool_observation", **item})

    reason_codes: list[str] = []
    severity = str(finding.get("severity") or "").strip().lower()
    bound_contract = finding.get("bound_evidence_contract") if isinstance(finding.get("bound_evidence_contract"), dict) else {}
    bound_status = str(bound_contract.get("status") or "").strip().lower()
    matched_bound_evidence = [
        str(item).strip()
        for item in bound_contract.get("matched_required_evidence") or []
        if str(item).strip()
    ]
    has_bound_attribution = bool(
        finding.get("covered_rules")
        or finding.get("rule_id")
        or finding.get("checkpoint_id")
    )
    unsupported_bound_claim = bool(
        has_bound_attribution
        and bound_status == "weak"
        and not matched_bound_evidence
        and not (tool_observations or [])
    )
    high_severity_gaps: list[str] = []
    if severity in {"critical", "high"}:
        if not changed_location:
            high_severity_gaps.append("changed_location_missing")
        if not triggers:
            high_severity_gaps.append("trigger_condition_missing")
        if not impact:
            high_severity_gaps.append("impact_missing")
        if paths and semantic_strength < 0.5:
            high_severity_gaps.append("trusted_semantic_path_missing")
            high_severity_gaps.append("heuristic_semantic_path")

    if counter_evidence:
        status: EvidenceStatus = "rejected_with_reason"
        reason_codes.extend(_contradiction_reason(item) for item in counter_evidence)
    elif unsupported_bound_claim:
        status = "rejected_with_reason"
        reason_codes.append("bound_required_evidence_missing")
    elif context_score <= 0.3 or not direct or unresolved_context:
        status = "unresolved_context"
        reason_codes.append("context_incomplete")
        reason_codes.extend(unresolved_context)
    elif high_severity_gaps:
        status = "needs_review"
        reason_codes.extend(high_severity_gaps)
    elif paths and semantic_strength < 0.5:
        status = "needs_review"
        reason_codes.append("heuristic_semantic_path")
    elif (not paths or semantic_strength >= 0.8) and trigger_score >= 0.7 and context_score >= 0.8:
        status = "confirmed"
        reason_codes.append("strong_evidence_chain")
    else:
        status = "needs_review"
        reason_codes.append("evidence_chain_incomplete")

    return EvidencePack(
        version="evidence_pack_v2",
        status=status,
        changed_location=changed_location,
        root_cause=root_cause,
        impact=impact,
        direct_evidence=tuple(direct),
        supporting_evidence=tuple(direct),
        semantic_paths=tuple(paths),
        trigger_conditions=triggers,
        contradictions=tuple(counter_evidence),
        verifier_results=tuple(item for item in tool_observations or [] if isinstance(item, dict)),
        unresolved_context=unresolved_context,
        semantic_path_strength=semantic_strength,
        trigger_specificity=trigger_score,
        contradiction_penalty=contradiction_penalty,
        context_completeness=context_score,
        reason_codes=tuple(dict.fromkeys(reason_codes)),
    )
