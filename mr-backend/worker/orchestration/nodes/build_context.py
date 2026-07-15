from __future__ import annotations

from pathlib import Path
from typing import Any

from context.context_metrics import context_health_from_state
from context.context_planner import plan_context_units
from context.semantic_graph import SemanticGraph, semantic_graph_from_record, semantic_graph_from_tree_sitter
from tools.gitnexus_tool import impact_paths
from tools.tree_sitter_tool import build_graph
from context.skill_requirements import collect_skill_context_requirements


def build_context_node(worktree: Path, changed_files: list[str], fallback_context: dict[str, Any]) -> dict[str, Any]:
    return {
        **fallback_context,
        "tree_sitter": build_graph(worktree),
        "gitnexus": impact_paths(worktree, changed_files),
    }


def make_build_context_node(*, recorder: Any, project_config: dict[str, Any] | None = None):
    def build_structured_context_node(state: dict[str, Any]) -> dict[str, Any]:
        span = recorder.span("build_context", "context_builder")
        diff_slices = state.get("diff_slices") or []
        code_context = state.get("code_context") or {}
        tool_observations = state.get("tool_observations") or []
        worktree_path = str(state.get("source_worktree_path") or "").strip()
        quality = (project_config or {}).get("review_quality") if isinstance((project_config or {}).get("review_quality"), dict) else {}
        semantic_index = str(quality.get("semantic_index") or "tree_sitter")
        priority_paths = [
            str(getattr(item, "filename", "") or (item.get("filename") if isinstance(item, dict) else ""))
            for item in (state.get("llm_files") or state.get("files") or [])
        ]
        semantic_graph_record = state.get("semantic_graph_record") if isinstance(state.get("semantic_graph_record"), dict) else {}
        raw_semantic_graph = build_graph(Path(worktree_path), {"include_paths": priority_paths}) if worktree_path and semantic_index != "regex" else {"status": "regex_selected", "parse_errors": []}
        if worktree_path and semantic_index != "regex":
            semantic_graph = semantic_graph_from_tree_sitter(raw_semantic_graph)
        elif semantic_index != "regex" and semantic_graph_record:
            semantic_graph = semantic_graph_from_record(semantic_graph_record)
        else:
            semantic_graph = SemanticGraph.empty()
        if semantic_index == "typed" and semantic_graph.status != "unavailable":
            semantic_graph = SemanticGraph(
                nodes=semantic_graph.nodes,
                edges=semantic_graph.edges,
                status="partial",
                degradations=(*semantic_graph.degradations, {"reason": "typed_index_unavailable", "fallback": "tree_sitter"}),
            )
        skill_requirements = collect_skill_context_requirements(state.get("selected_agents") or [])

        def load_frozen_source(file_path: str) -> str:
            if not worktree_path:
                return ""
            root = Path(worktree_path).resolve()
            relative = Path(str(file_path or "").replace("\\", "/"))
            if relative.is_absolute() or ".." in relative.parts:
                return ""
            target = (root / relative).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                return ""
            if not target.is_file() or target.stat().st_size > 512 * 1024:
                return ""
            return target.read_text("utf-8", errors="replace")

        context_plan = plan_context_units(
            state.get("llm_files") or state.get("files") or [],
            source_file_contents=state.get("source_file_contents") or {},
            related_context=state.get("related_context") or {},
            semantic_graph=semantic_graph,
            source_loader=load_frozen_source,
            skill_checkpoint_ids=list(skill_requirements.checkpoint_ids),
            context_queries=list(skill_requirements.context_queries),
            max_dependency_hops=skill_requirements.max_dependency_hops,
        )
        enriched_state = {
            **state,
            "context_units": list(context_plan.units),
            "unresolved_context_units": list(context_plan.unresolved),
            "context_plan": context_plan.to_record(),
            "semantic_graph": semantic_graph,
            "semantic_graph_record": semantic_graph.to_record(),
            "skill_context_requirements": skill_requirements.to_record(),
        }
        context_health = context_health_from_state(enriched_state)
        context_bundle = {
            "diff_slices": diff_slices,
            "code_context": code_context,
            "related_context": state.get("related_context") or {},
            "tool_observations": tool_observations,
            "context_health": context_health,
            "context_plan": context_plan.to_record(),
            "semantic_graph": semantic_graph.to_record(),
            "skill_context_requirements": skill_requirements.to_record(),
        }
        recorder.event(
            span,
            "structured_context_ready",
            f"结构化上下文就绪：{len(diff_slices)} 个 diff slice，{len(tool_observations)} 个工具观察",
            {
                "diff_slice_count": len(diff_slices),
                "tool_observation_count": len(tool_observations),
                "code_context_status": code_context.get("status"),
                "related_symbol_count": len((state.get("related_context") or {}).get("modified_symbols") or []),
                "context_health": context_health,
            },
        )
        recorder.finish(span)
        return {**enriched_state, "context_bundle": context_bundle, "context_health": context_health}

    return build_structured_context_node
