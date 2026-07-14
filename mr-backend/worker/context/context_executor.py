from __future__ import annotations

from typing import Any, Callable


def _dependency_record(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        source = item.get("source") if isinstance(item.get("source"), dict) else item
        return {
            "symbol_id": str(item.get("symbol_id") or ""),
            "relation": str(item.get("relation") or ""),
            "file_path": str(source.get("file_path") or item.get("file_path") or ""),
            "confidence": str(item.get("confidence") or "heuristic"),
        }
    source = getattr(item, "source", None)
    return {
        "symbol_id": str(getattr(item, "symbol_id", "") or ""),
        "relation": str(getattr(item, "relation", "") or ""),
        "file_path": str(getattr(source, "file_path", "") or ""),
        "confidence": str(getattr(item, "confidence", "heuristic") or "heuristic"),
    }


def _attach_semantic_paths(finding: dict[str, Any], unit: Any) -> None:
    dependencies = [
        _dependency_record(item)
        for item in (getattr(unit, "dependencies", ()) or (unit.get("dependencies") if isinstance(unit, dict) else []))
    ]
    by_identity = {
        (item["symbol_id"], item["relation"], item["file_path"]): item
        for item in dependencies
        if item["symbol_id"] and item["relation"] and item["file_path"]
    }
    claims = [item for item in finding.get("semantic_evidence") or [] if isinstance(item, dict)]
    validated: list[dict[str, Any]] = []
    for claim in claims:
        key = (
            str(claim.get("symbol_id") or ""),
            str(claim.get("relation") or ""),
            str(claim.get("file_path") or ""),
        )
        dependency = by_identity.get(key)
        if dependency:
            validated.append({
                "source_id": "context_unit_primary",
                "target_id": dependency["symbol_id"],
                "relation": dependency["relation"],
                "file_path": dependency["file_path"],
                "confidence": dependency["confidence"],
                "resolver": "context_planner_validated",
            })
    finding["semantic_paths"] = [{"complete": len(validated) == len(claims), "edges": validated}] if validated else []
    if claims and len(validated) != len(claims):
        unresolved = [str(item) for item in finding.get("unresolved_context") or [] if str(item)]
        finding["unresolved_context"] = list(dict.fromkeys([*unresolved, "semantic_evidence_unresolved"]))


def call_llm_for_context_units(
    *,
    call_llm: Callable[..., list[dict[str, Any]]],
    config: dict[str, Any],
    recorder: Any,
    span: Any,
    agent: dict[str, Any],
    files: list[Any],
    skill_summary: str,
    context_units: list[Any],
    budget_tracker: Any = None,
    ensure_active: Callable[[], None] | None = None,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, str]]]:
    if not context_units:
        if ensure_active:
            ensure_active()
        return call_llm(config, recorder, span, agent, files, skill_summary), [], []

    findings: list[dict[str, Any]] = []
    executed: list[str] = []
    unresolved: list[dict[str, str]] = []
    for unit in context_units:
        if ensure_active:
            ensure_active()
        unit_id = str(getattr(unit, "unit_id", "") or (unit.get("unit_id") if isinstance(unit, dict) else ""))
        if budget_tracker and budget_tracker.should_stop():
            unresolved.append({"unit_id": unit_id, "reason": "unresolved_budget"})
            continue
        unit_agent = {**agent, "context_unit": unit}
        unit_findings = call_llm(config, recorder, span, unit_agent, files, skill_summary)
        context_hash = str(getattr(unit, "context_hash", "") or (unit.get("context_hash") if isinstance(unit, dict) else ""))
        hunk_ids = list(getattr(unit, "hunk_ids", ()) or (unit.get("hunk_ids") if isinstance(unit, dict) else []))
        for finding in unit_findings:
            _attach_semantic_paths(finding, unit)
            finding["context_unit_id"] = unit_id
            finding["context_hash"] = context_hash
            finding["context_hunk_ids"] = hunk_ids
        findings.extend(unit_findings)
        executed.append(unit_id)
    return findings, executed, unresolved
