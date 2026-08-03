from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from context.context_unit import ContextUnit, DependencyRef, SourceRange
from context.change_intent import classify_change_intent
from context.semantic_graph import SemanticGraph
from diff.slicer import diff_hunks_by_file


PLANNER_VERSION = "context_planner_v2"


@dataclass(frozen=True)
class ContextPlan:
    units: tuple[ContextUnit, ...]
    assigned_hunk_ids: tuple[str, ...]
    unresolved: tuple[dict[str, str], ...]
    diff_assignment_rate: float
    plan_hash: str

    def to_record(self) -> dict[str, Any]:
        return {
            "version": PLANNER_VERSION,
            "plan_hash": self.plan_hash,
            "diff_assignment_rate": self.diff_assignment_rate,
            "assigned_hunk_ids": list(self.assigned_hunk_ids),
            "unresolved": list(self.unresolved),
            "units": [unit.to_prompt_item() for unit in self.units],
        }


def _value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hunk_id(file_path: str, start: int, end: int) -> str:
    return "hunk_" + _sha256(f"{file_path}:{start}:{end}")[:16]


def _symbol_ranges(related_context: dict[str, Any], file_path: str) -> list[tuple[str, int, int]]:
    result: list[tuple[str, int, int]] = []
    for key in ("changed_symbols", "modified_symbols"):
        for symbol in related_context.get(key) or []:
            if not isinstance(symbol, dict):
                continue
            symbol_file = str(
                symbol.get("definition_file") or symbol.get("file_path") or symbol.get("file") or symbol.get("path") or ""
            )
            if symbol_file != file_path:
                continue
            try:
                start = int(symbol.get("line_start") or symbol.get("definition_line") or symbol.get("start_line") or symbol.get("line") or 0)
                end = int(symbol.get("line_end") or symbol.get("end_line") or start)
            except (TypeError, ValueError):
                continue
            if start > 0:
                result.append((str(symbol.get("symbol_id") or symbol.get("name") or f"{file_path}:{start}"), start, max(start, end)))
    return sorted(set(result), key=lambda item: (item[1], item[2], item[0]))


def _enclosing_symbol(symbols: list[tuple[str, int, int]], start: int, end: int) -> tuple[str, int, int] | None:
    matches = [item for item in symbols if item[1] <= start and item[2] >= end]
    return min(matches, key=lambda item: item[2] - item[1]) if matches else None


def _patch_for_range(patch: str, start: int, end: int) -> str:
    selected: list[str] = []
    include = False
    for line in patch.splitlines():
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if not match:
                include = False
            else:
                hunk_start = int(match.group(1))
                hunk_length = int(match.group(2) or 1)
                hunk_end = hunk_start + max(1, hunk_length) - 1
                include = hunk_start <= end and hunk_end >= start
        if include:
            selected.append(line)
    return "\n".join(selected) or patch


def _source_window(source: str, start: int, end: int, *, window: int, max_lines: int) -> tuple[str, int, int]:
    lines = source.splitlines()
    if not lines:
        return "", start, end
    range_start = max(1, start - window)
    range_end = min(len(lines), end + window)
    if range_end - range_start + 1 > max_lines:
        center = (start + end) // 2
        half = max_lines // 2
        range_start = max(1, center - half)
        range_end = min(len(lines), range_start + max_lines - 1)
        range_start = max(1, range_end - max_lines + 1)
    numbered = [f"{line_no}: {lines[line_no - 1]}" for line_no in range(range_start, range_end + 1)]
    return "\n".join(numbered), range_start, range_end


def _edge_allowed(kind: str, queries: set[str]) -> bool:
    if not queries:
        return True
    mapping = {
        "calls": {"callers", "callees"},
        "implements": {"implementations"},
        "extends": {"implementations"},
        "overrides": {"implementations"},
        "tested_by": {"tests"},
        "reads_config": {"config_refs"},
    }
    return bool(mapping.get(kind, set()) & queries)


def _related_semantic_nodes(graph: SemanticGraph, start_node_id: str, queries: set[str], max_hops: int) -> list[tuple[Any, Any]]:
    result: list[tuple[Any, Any]] = []
    frontier = [(start_node_id, 0)]
    visited = {start_node_id}
    while frontier:
        node_id, depth = frontier.pop(0)
        if depth >= max_hops:
            continue
        for edge in graph.incoming(node_id) + graph.outgoing(node_id):
            if not _edge_allowed(edge.kind, queries):
                continue
            related_id = edge.source_id if edge.target_id == node_id else edge.target_id
            if related_id in visited:
                continue
            visited.add(related_id)
            try:
                related = graph.node(related_id)
            except KeyError:
                continue
            result.append((edge, related))
            frontier.append((related_id, depth + 1))
    return result


def plan_context_units(
    files: list[Any],
    *,
    source_file_contents: dict[str, str],
    related_context: dict[str, Any],
    semantic_graph: SemanticGraph | None = None,
    source_loader: Callable[[str], str] | None = None,
    skill_checkpoint_ids: list[str] | None = None,
    source_window_lines: int = 40,
    max_source_lines_per_unit: int = 400,
    context_queries: list[str] | tuple[str, ...] | None = None,
    max_dependency_hops: int = 1,
) -> ContextPlan:
    hunks_by_file = diff_hunks_by_file(files)
    file_by_path = {str(_value(item, "filename")): item for item in files}
    planned: list[ContextUnit] = []
    assigned: list[str] = []
    unresolved: list[dict[str, str]] = []

    for file_path in sorted(hunks_by_file):
        changed = file_by_path[file_path]
        patch = str(_value(changed, "patch"))
        source = str(source_file_contents.get(file_path) or "")
        symbols = _symbol_ranges(related_context, file_path)
        symbol_ids = {item[0] for item in symbols}
        groups: dict[tuple[str, int, int], list[tuple[int, int, str]]] = {}
        for start, end in hunks_by_file[file_path]:
            hunk_id = _hunk_id(file_path, start, end)
            symbol = _enclosing_symbol(symbols, start, end)
            # A single method/class can be thousands of lines long. Grouping distant
            # hunks into one fixed-size center window would omit both changed areas.
            # Split oversized symbols per hunk; the source window then gives each
            # semantic slice an audited 40-line overlap around its changed range.
            if symbol and symbol[2] - symbol[1] + 1 > max_source_lines_per_unit:
                group_key = (symbol[0], start, end)
            else:
                group_key = symbol if symbol else (f"{file_path}:{start}-{end}", start, end)
            groups.setdefault(group_key, []).append((start, end, hunk_id))

        for (symbol_id, symbol_start, symbol_end), group_hunks in groups.items():
            hunk_start = min(item[0] for item in group_hunks)
            hunk_end = max(item[1] for item in group_hunks)
            matched_symbol = symbol_id in symbol_ids
            requested_start = symbol_start if matched_symbol else hunk_start
            requested_end = symbol_end if matched_symbol else hunk_end
            fallback_reason = ""
            if source:
                source_text, actual_start, actual_end = _source_window(
                    source,
                    requested_start,
                    requested_end,
                    window=source_window_lines,
                    max_lines=max_source_lines_per_unit,
                )
                if not matched_symbol:
                    fallback_reason = "no_symbol"
            else:
                source_text = _patch_for_range(patch, hunk_start, hunk_end)
                actual_start, actual_end = hunk_start, hunk_end
                fallback_reason = "no_full_source"
            if not source_text:
                unresolved.extend({"hunk_id": item[2], "reason": "unresolved_source"} for item in group_hunks)
                continue
            content_hash = _sha256(source_text)
            hunk_ids = tuple(item[2] for item in group_hunks)
            patch_text = _patch_for_range(patch, hunk_start, hunk_end)
            change_intent = classify_change_intent(
                file_path,
                patch_text,
                status=str(_value(changed, "status", "modified")),
            )
            semantic_nodes = [
                node
                for node in (semantic_graph.nodes if semantic_graph else ())
                if node.file_path == file_path and node.line_start <= hunk_end and node.line_end >= hunk_start
            ]
            dependencies: list[DependencyRef] = []
            query_set = {str(item) for item in context_queries or [] if str(item)}
            bounded_hops = max(1, min(3, int(max_dependency_hops or 1)))
            for node in semantic_nodes:
                related_nodes = _related_semantic_nodes(semantic_graph, node.node_id, query_set, bounded_hops) if semantic_graph else []
                for edge, related_node in related_nodes:
                    if related_node.file_path == file_path:
                        continue
                    related_source = str(source_file_contents.get(related_node.file_path) or "")
                    if not related_source and source_loader:
                        try:
                            related_source = str(source_loader(related_node.file_path) or "")
                        except (OSError, ValueError):
                            related_source = ""
                    related_hash = _sha256(related_source) if related_source else ""
                    dependency_text = ""
                    if related_source:
                        dependency_text, _, _ = _source_window(
                            related_source,
                            related_node.line_start,
                            related_node.line_end,
                            window=12,
                            max_lines=80,
                        )
                    dependency = DependencyRef(
                        relation=edge.kind,
                        symbol_id=related_node.node_id,
                        source=SourceRange(
                            related_node.file_path,
                            related_node.line_start,
                            related_node.line_end,
                            related_hash,
                        ),
                        confidence=edge.confidence,
                        source_text=dependency_text,
                    )
                    if dependency not in dependencies:
                        dependencies.append(dependency)
                    if len(dependencies) >= 30:
                        break
                if len(dependencies) >= 30:
                    break
            resolved_symbol_ids = tuple(sorted({node.node_id for node in semantic_nodes}))
            context_hash = _sha256(
                json.dumps(
                    {
                        "version": PLANNER_VERSION,
                        "file_path": file_path,
                        "range": [actual_start, actual_end],
                        "hunk_ids": hunk_ids,
                        "symbol_id": symbol_id,
                        "source_hash": content_hash,
                        "change_intent": change_intent.to_dict(),
                        "checkpoints": sorted(skill_checkpoint_ids or []),
                        "context_queries": sorted(query_set),
                        "max_dependency_hops": bounded_hops,
                        "dependencies": [
                            {
                                "relation": item.relation,
                                "symbol_id": item.symbol_id,
                                "confidence": item.confidence,
                                "content_hash": item.source.content_hash,
                            }
                            for item in dependencies
                        ],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            planned.append(
                ContextUnit(
                    unit_id="ctx_" + context_hash[:16],
                    hunk_ids=hunk_ids,
                    primary_source=SourceRange(file_path, actual_start, actual_end, content_hash),
                    changed_symbol_ids=resolved_symbol_ids or ((symbol_id,) if matched_symbol else ()),
                    source_text=source_text,
                    patch_text=patch_text,
                    change_intent=change_intent,
                    dependencies=tuple(dependencies),
                    skill_checkpoint_ids=tuple(sorted(skill_checkpoint_ids or [])),
                    token_estimate=max(1, (len(source_text) + len(patch_text)) // 4),
                    fallback_reason=fallback_reason,
                    context_hash=context_hash,
                )
            )
            assigned.extend(hunk_ids)

    all_hunk_count = sum(len(items) for items in hunks_by_file.values())
    diff_assignment_rate = round(len(set(assigned)) / all_hunk_count, 4) if all_hunk_count else 1.0
    plan_hash = _sha256("|".join(sorted(unit.context_hash for unit in planned)) + "|" + PLANNER_VERSION)
    return ContextPlan(
        units=tuple(sorted(planned, key=lambda unit: (unit.primary_source.file_path, unit.primary_source.line_start, unit.unit_id))),
        assigned_hunk_ids=tuple(sorted(set(assigned))),
        unresolved=tuple(unresolved),
        diff_assignment_rate=diff_assignment_rate,
        plan_hash=plan_hash,
    )
