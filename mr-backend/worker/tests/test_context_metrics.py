from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

from context.context_metrics import context_health_from_state, summarize_context_coverage  # noqa: E402
from config import normalize_review_quality_config  # noqa: E402
from orchestration.nodes.build_context import make_build_context_node  # noqa: E402
from orchestration.nodes.finalize import attach_context_coverage  # noqa: E402


class FakeRecorder:
    def span(self, *_args):
        return "span"

    def event(self, *_args):
        return None

    def finish(self, *_args):
        return None


@dataclass
class ChangedFile:
    filename: str
    patch: str


def test_context_metrics_exposes_unassigned_and_unresolved_hunks() -> None:
    metrics = summarize_context_coverage(
        total=20,
        assigned=16,
        unresolved_source=2,
        unresolved_budget=2,
    )

    assert metrics["diff_assignment_rate"] == 0.8
    assert metrics["unresolved_hunk_count"] == 4
    assert metrics["status"] == "partial"


def test_context_health_reports_patch_only_degradation() -> None:
    state = {
        "files": [object(), object()],
        "llm_files": [object()],
        "source_file_contents": {},
        "source_worktree_path": None,
        "source_worktree_errors": [{"reason": "clone_failed"}],
        "diff_slices": [{"hunk_ids": ["h1"]}, {"hunk_ids": ["h2"]}],
        "related_context": {"status": "fallback", "modified_symbols": []},
    }

    metrics = context_health_from_state(state)

    assert metrics["worktree_mode"] == "patch_only"
    assert metrics["source_fetch_rate"] == 0.0
    assert metrics["context_units_unresolved"] >= 1
    assert metrics["status"] == "patch_only"
    assert metrics["context_engine"] == "v2"


def test_build_context_node_attaches_context_health() -> None:
    node = make_build_context_node(recorder=FakeRecorder())
    state = node(
        {
            "files": [],
            "llm_files": [],
            "source_file_contents": {},
            "source_worktree_path": "/tmp/repo",
            "source_worktree_errors": [],
            "diff_slices": [],
            "code_context": {},
            "related_context": {},
            "tool_observations": [],
        }
    )

    assert state["context_health"]["status"] == "full"
    assert state["context_bundle"]["context_health"] == state["context_health"]


def test_finalize_coverage_preserves_context_health() -> None:
    coverage = attach_context_coverage(
        {"finding_count": 2},
        {"context_health": {"status": "partial", "diff_assignment_rate": 0.9}},
    )

    assert coverage["finding_count"] == 2
    assert coverage["context_health"]["status"] == "partial"


def test_context_health_counts_hunks_not_context_unit_containers() -> None:
    metrics = context_health_from_state(
        {
            "files": [ChangedFile("src/A.java", "")],
            "llm_files": [ChangedFile("src/A.java", "")],
            "source_file_contents": {"src/A.java": "source"},
            "source_worktree_path": "/tmp/repo",
            "source_worktree_errors": [],
            "context_units": [{"unit_id": "unit-1", "hunk_ids": ["h1", "h2"]}],
            "unresolved_context_units": [],
            "context_plan": {
                "assigned_hunk_ids": ["h1", "h2"],
                "unresolved": [],
                "diff_assignment_rate": 1.0,
            },
            "related_context": {},
        }
    )

    assert metrics["diff_hunk_count"] == 2
    assert metrics["assigned_hunk_count"] == 2
    assert metrics["diff_assignment_rate"] == 1.0


def test_context_health_uses_semantic_graph_as_symbol_resolution_fallback() -> None:
    metrics = context_health_from_state(
        {
            "files": [ChangedFile("src/A.java", ""), ChangedFile("src/B.java", "")],
            "llm_files": [ChangedFile("src/A.java", ""), ChangedFile("src/B.java", "")],
            "source_file_contents": {"src/A.java": "source", "src/B.java": "source"},
            "source_worktree_path": None,
            "source_worktree_errors": [],
            "context_units": [],
            "related_context": {"status": "resolved", "changed_symbols": []},
            "semantic_graph_record": {
                "status": "full",
                "nodes": [
                    {"node_id": "a", "kind": "function", "name": "a", "file_path": "src/A.java", "line_start": 1, "line_end": 2},
                    {"node_id": "b", "kind": "function", "name": "b", "file_path": "src/B.java", "line_start": 1, "line_end": 2},
                ],
                "edges": [],
                "degradations": [],
            },
        }
    )

    assert metrics["changed_symbol_resolution_rate"] == 1.0


def test_build_context_creates_executable_context_units() -> None:
    changed = ChangedFile("src/A.java", "@@ -1,1 +1,1 @@\n-old\n+new")
    node = make_build_context_node(recorder=FakeRecorder())
    state = node(
        {
            "files": [changed],
            "llm_files": [changed],
            "source_file_contents": {"src/A.java": "new\n"},
            "source_worktree_path": "/tmp/repo",
            "source_worktree_errors": [],
            "diff_slices": [{"file_path": "src/A.java"}],
            "code_context": {},
            "related_context": {},
            "tool_observations": [],
        }
    )

    assert len(state["context_units"]) == 1
    assert state["context_plan"]["diff_assignment_rate"] == 1.0
    assert state["context_health"]["context_engine"] == "v2"
    assert state["semantic_graph_record"]["version"] == "semantic_graph_v2"


def test_legacy_v1_setting_cannot_disable_v2_context_units() -> None:
    changed = ChangedFile("src/A.java", "@@ -1,1 +1,1 @@\n-old\n+new")
    node = make_build_context_node(
        recorder=FakeRecorder(),
        project_config={"review_quality": {"context_engine": "v1"}},
    )
    state = node(
        {
            "files": [changed],
            "llm_files": [changed],
            "source_file_contents": {"src/A.java": "new\n"},
            "source_worktree_path": "/tmp/repo",
            "source_worktree_errors": [],
            "diff_slices": [{"file_path": "src/A.java"}],
            "code_context": {},
            "related_context": {},
            "tool_observations": [],
        }
    )

    assert len(state["context_units"]) == 1
    assert state["context_health"]["context_engine"] == "v2"


def test_review_quality_normalization_ignores_removed_dual_engine_fields() -> None:
    quality = normalize_review_quality_config(
        {
            "review_quality": {
                "context_engine": "v1",
                "quality_shadow_mode": True,
                "auto_shadow_baseline": True,
                "auto_rollback_enabled": True,
                "minimum_distinct_mrs": 30,
                "gold_dataset_path": "old-gold.jsonl",
                "semantic_index": "typed",
                "llm_replay": "replay",
            }
        }
    )

    assert quality == {"semantic_index": "typed", "llm_replay": "replay"}


if __name__ == "__main__":
    test_context_metrics_exposes_unassigned_and_unresolved_hunks()
    test_context_health_reports_patch_only_degradation()
    test_build_context_node_attaches_context_health()
    test_finalize_coverage_preserves_context_health()
    test_context_health_counts_hunks_not_context_unit_containers()
    test_context_health_uses_semantic_graph_as_symbol_resolution_fallback()
    test_build_context_creates_executable_context_units()
    test_legacy_v1_setting_cannot_disable_v2_context_units()
    test_review_quality_normalization_ignores_removed_dual_engine_fields()
    print("context metrics tests passed")
