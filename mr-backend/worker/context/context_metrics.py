from __future__ import annotations

from typing import Any


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return round(max(0, numerator) / denominator, 4)


def summarize_context_coverage(
    *,
    total: int,
    assigned: int,
    unresolved_source: int = 0,
    unresolved_budget: int = 0,
) -> dict[str, Any]:
    total = max(0, int(total))
    assigned = max(0, min(int(assigned), total))
    unresolved_source = max(0, int(unresolved_source))
    unresolved_budget = max(0, int(unresolved_budget))
    unresolved = max(total - assigned, unresolved_source + unresolved_budget)
    if total == 0:
        status = "full"
    elif assigned >= total and unresolved == 0:
        status = "full"
    else:
        status = "partial"
    return {
        "diff_hunk_count": total,
        "assigned_hunk_count": assigned,
        "diff_assignment_rate": _rate(assigned, total),
        "unresolved_source_count": unresolved_source,
        "unresolved_budget_count": unresolved_budget,
        "unresolved_hunk_count": unresolved,
        "status": status,
    }


def _filename(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("filename") or item.get("file_path") or "")
    return str(getattr(item, "filename", "") or "")


def context_health_from_state(state: dict[str, Any]) -> dict[str, Any]:
    files = list(state.get("files") or [])
    llm_files = list(state.get("llm_files") or [])
    source_contents = dict(state.get("source_file_contents") or {})
    source_worktree_path = str(state.get("source_worktree_path") or "").strip()
    worktree_errors = list(state.get("source_worktree_errors") or [])
    diff_slices = list(state.get("diff_slices") or [])
    context_units = list(state.get("context_units") or [])
    unresolved_units = list(state.get("unresolved_context_units") or [])
    related_context = state.get("related_context") if isinstance(state.get("related_context"), dict) else {}
    semantic_graph_record = state.get("semantic_graph_record") if isinstance(state.get("semantic_graph_record"), dict) else {}
    context_plan = state.get("context_plan") if isinstance(state.get("context_plan"), dict) else {}

    if source_worktree_path and not worktree_errors:
        worktree_mode = "full"
    elif source_worktree_path:
        worktree_mode = "partial"
    else:
        worktree_mode = "patch_only"

    changed_filenames = {_filename(item) for item in files if _filename(item)}
    fetched_filenames = changed_filenames & set(source_contents)
    total_files = len(changed_filenames) or len(files)
    source_fetch_rate = _rate(len(fetched_filenames), total_files)

    modified_symbols = [item for item in related_context.get("modified_symbols") or [] if isinstance(item, dict)]
    changed_symbols = [item for item in related_context.get("changed_symbols") or [] if isinstance(item, dict)]
    symbol_files = {
        str(item.get("definition_file") or item.get("file_path") or item.get("file") or "")
        for item in modified_symbols + changed_symbols
        if str(item.get("definition_file") or item.get("file_path") or item.get("file") or "")
    }
    graph_nodes = (
        semantic_graph_record.get("nodes")
        if isinstance(semantic_graph_record, dict)
        else []
    )
    symbol_files.update(
        {
            str(item.get("file_path") or "")
            for item in graph_nodes or []
            if isinstance(item, dict)
            and str(item.get("file_path") or "")
            and str(item.get("kind") or "") in {"class", "interface", "function", "config", "schema", "test"}
        }
    )
    changed_symbol_resolution_rate = _rate(len(symbol_files & changed_filenames), total_files)
    related_status = str(related_context.get("status") or "unavailable")
    semantic_status = str(semantic_graph_record.get("status") or "")
    if semantic_status == "full":
        semantic_parse_rate = 1.0
    elif semantic_status == "partial":
        semantic_parse_rate = 0.5
    else:
        semantic_parse_rate = 1.0 if related_status in {"indexed", "cached", "available", "resolved"} else 0.0

    if context_units:
        assigned_hunk_ids = {
            str(item)
            for item in context_plan.get("assigned_hunk_ids") or []
            if str(item)
        }
        if not assigned_hunk_ids:
            assigned_hunk_ids = {
                str(hunk_id)
                for unit in context_units
                for hunk_id in ((unit.get("hunk_ids") or []) if isinstance(unit, dict) else (getattr(unit, "hunk_ids", ()) or ()))
                if str(hunk_id)
            }
        plan_unresolved = [item for item in context_plan.get("unresolved") or [] if isinstance(item, dict)]
        unresolved_hunk_ids = {str(item.get("hunk_id") or "") for item in plan_unresolved if str(item.get("hunk_id") or "")}
        total_hunks = len(assigned_hunk_ids | unresolved_hunk_ids)
        assignment = summarize_context_coverage(
            total=total_hunks,
            assigned=len(assigned_hunk_ids),
            unresolved_source=sum(1 for item in plan_unresolved if str(item.get("reason") or "") == "unresolved_source"),
            unresolved_budget=0,
        )
    else:
        assignment = summarize_context_coverage(total=len(diff_slices), assigned=len(diff_slices))

    patch_only_unresolved = max(0, total_files - len(fetched_filenames)) if worktree_mode == "patch_only" else 0
    unresolved_count = max(len(unresolved_units), assignment["unresolved_hunk_count"], patch_only_unresolved)
    if worktree_mode == "patch_only":
        status = "patch_only"
    elif worktree_mode == "partial" or unresolved_count:
        status = "partial"
    else:
        status = "full"

    return {
        "version": "context_health_v1",
        "context_engine": "v2",
        "worktree_mode": worktree_mode,
        "worktree_error_count": len(worktree_errors),
        "changed_file_count": total_files,
        "llm_file_count": len(llm_files),
        "source_file_count": len(fetched_filenames),
        "source_fetch_rate": source_fetch_rate,
        "semantic_parse_rate": semantic_parse_rate,
        "changed_symbol_resolution_rate": changed_symbol_resolution_rate,
        "diff_assignment_rate": assignment["diff_assignment_rate"],
        "diff_hunk_count": assignment["diff_hunk_count"],
        "assigned_hunk_count": assignment["assigned_hunk_count"],
        "context_units_total": len(context_units),
        "context_units_executed": len({str(item) for item in state.get("executed_context_unit_ids") or [] if str(item)}),
        "context_units_unresolved": unresolved_count,
        "related_context_status": related_status,
        "status": status,
    }
