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


def _unit_value(unit: Any, name: str, default: Any = "") -> Any:
    if isinstance(unit, dict):
        return unit.get(name, default)
    return getattr(unit, name, default)


def _unit_id(unit: Any) -> str:
    return str(_unit_value(unit, "unit_id", "") or "")


def _unit_context_hash(unit: Any) -> str:
    return str(_unit_value(unit, "context_hash", "") or "")


def _unit_hunk_ids(unit: Any) -> list[str]:
    return [str(item) for item in (_unit_value(unit, "hunk_ids", []) or []) if str(item)]


def _unit_file_range(unit: Any) -> tuple[str, int, int]:
    primary = _unit_value(unit, "primary_source", None)
    if isinstance(primary, dict):
        file_path = str(primary.get("file_path") or "")
        start = int(primary.get("line_start") or 0)
        end = int(primary.get("line_end") or start or 0)
        return file_path, start, end
    if primary is not None:
        file_path = str(getattr(primary, "file_path", "") or "")
        start = int(getattr(primary, "line_start", 0) or 0)
        end = int(getattr(primary, "line_end", start) or start or 0)
        return file_path, start, end
    return str(_unit_value(unit, "file_path", "") or ""), int(_unit_value(unit, "line_start", 0) or 0), int(_unit_value(unit, "line_end", 0) or 0)


def _matching_unit(finding: dict[str, Any], units: list[Any]) -> Any | None:
    explicit_id = str(finding.get("context_unit_id") or "").strip()
    by_id = {_unit_id(unit): unit for unit in units if _unit_id(unit)}
    if explicit_id and explicit_id in by_id:
        return by_id[explicit_id]
    file_path = str(finding.get("file_path") or "")
    try:
        line_start = int(finding.get("line_start") or 0)
    except (TypeError, ValueError):
        line_start = 0
    matches = []
    for unit in units:
        unit_file, unit_start, unit_end = _unit_file_range(unit)
        if unit_file == file_path and unit_start <= line_start <= max(unit_start, unit_end):
            matches.append(unit)
    if len(matches) == 1:
        return matches[0]
    return None


def _context_unit_batch_size(config: dict[str, Any], agent: dict[str, Any]) -> int:
    quality = config.get("review_quality") if isinstance(config.get("review_quality"), dict) else {}
    execution = config.get("review_execution") if isinstance(config.get("review_execution"), dict) else {}
    raw = (
        agent.get("context_units_per_llm_call")
        or quality.get("context_units_per_llm_call")
        or execution.get("context_units_per_llm_call")
        or 6
    )
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 6
    return max(1, min(value, 10))


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


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
    batch_size = _context_unit_batch_size(config, agent)
    for unit_batch in _chunks(context_units, batch_size):
        if ensure_active:
            ensure_active()
        if budget_tracker and budget_tracker.should_stop():
            for unit in unit_batch:
                unresolved.append({"unit_id": _unit_id(unit), "reason": "unresolved_budget"})
            continue
        unit_agent = {**agent, "context_units": unit_batch}
        unit_findings = call_llm(config, recorder, span, unit_agent, files, skill_summary)
        for finding in unit_findings:
            matched_unit = _matching_unit(finding, unit_batch)
            if matched_unit is None and len(unit_batch) == 1:
                matched_unit = unit_batch[0]
            if matched_unit is not None:
                _attach_semantic_paths(finding, matched_unit)
                finding["context_unit_id"] = _unit_id(matched_unit)
                finding["context_hash"] = _unit_context_hash(matched_unit)
                finding["context_hunk_ids"] = _unit_hunk_ids(matched_unit)
        findings.extend(unit_findings)
        executed.extend(_unit_id(unit) for unit in unit_batch if _unit_id(unit))
    return findings, executed, unresolved
