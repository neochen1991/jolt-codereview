from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.gitnexus_tool import impact_paths
from tools.tree_sitter_tool import build_graph


def build_context_node(worktree: Path, changed_files: list[str], fallback_context: dict[str, Any]) -> dict[str, Any]:
    return {
        **fallback_context,
        "tree_sitter": build_graph(worktree),
        "gitnexus": impact_paths(worktree, changed_files),
    }


def make_build_context_node(*, recorder: Any):
    def build_structured_context_node(state: dict[str, Any]) -> dict[str, Any]:
        span = recorder.span("build_context", "context_builder")
        diff_slices = state.get("diff_slices") or []
        code_context = state.get("code_context") or {}
        tool_observations = state.get("tool_observations") or []
        context_bundle = {
            "diff_slices": diff_slices,
            "code_context": code_context,
            "related_context": state.get("related_context") or {},
            "tool_observations": tool_observations,
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
            },
        )
        recorder.finish(span)
        return {**state, "context_bundle": context_bundle}

    return build_structured_context_node
