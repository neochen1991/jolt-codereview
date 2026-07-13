from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

from context.context_planner import plan_context_units  # noqa: E402
from context.context_executor import call_llm_for_context_units  # noqa: E402
from context.semantic_graph import SemanticEdge, SemanticGraph, SemanticNode  # noqa: E402
from llm import client as llm_client  # noqa: E402
from prompts.builder import build_context_unit_prompt  # noqa: E402


@dataclass
class ChangedFile:
    filename: str
    patch: str
    status: str = "modified"
    additions: int = 1
    deletions: int = 0
    changes: int = 1


def _agent() -> dict:
    return {
        "agent_id": "coding_agent",
        "display_name": "Coding Agent",
        "applies_to": {"persona": "reviewer", "review_scope": "correctness"},
        "tool_observations": [],
        "bound_rules": [],
    }


def test_large_file_late_hunk_is_present_in_executable_context() -> None:
    lines = [f"line {index}" for index in range(1, 1201)]
    lines[949] = "LATE_BUG_SENTINEL = dangerous_call();"
    source = "\n".join(lines)
    changed = ChangedFile(
        "src/main/java/com/acme/LargeService.java",
        "@@ -949,1 +950,1 @@\n-LATE_BUG_SENTINEL = safe_call();\n+LATE_BUG_SENTINEL = dangerous_call();",
    )

    plan = plan_context_units(
        [changed],
        source_file_contents={changed.filename: source},
        related_context={},
    )

    assert plan.diff_assignment_rate == 1.0
    assert len(plan.units) == 1
    assert "LATE_BUG_SENTINEL" in plan.units[0].source_text
    prompt, _safety = build_context_unit_prompt(_agent(), plan.units[0], "")
    payload = json.loads(prompt)
    assert payload["structured_diff"]["format"] == "context_units_v2"
    assert "LATE_BUG_SENTINEL" in prompt


def test_distant_hunks_in_one_oversized_symbol_are_not_lost_by_center_crop() -> None:
    lines = [f"line {index}" for index in range(1, 1201)]
    lines[99] = "EARLY_BUG_SENTINEL = dangerous_early();"
    lines[1099] = "LATE_BUG_SENTINEL = dangerous_late();"
    filename = "src/main/java/com/acme/HugeMethod.java"
    changed = ChangedFile(
        filename,
        "@@ -99,1 +100,1 @@\n-oldEarly\n+EARLY_BUG_SENTINEL = dangerous_early();\n"
        "@@ -1099,1 +1100,1 @@\n-oldLate\n+LATE_BUG_SENTINEL = dangerous_late();",
    )
    related = {
        "changed_symbols": [
            {
                "symbol_id": "HugeMethod#process",
                "file_path": filename,
                "line_start": 1,
                "line_end": 1200,
            }
        ]
    }

    plan = plan_context_units(
        [changed],
        source_file_contents={filename: "\n".join(lines)},
        related_context=related,
        max_source_lines_per_unit=400,
    )

    assert plan.diff_assignment_rate == 1.0
    assert len(plan.units) == 2
    combined = "\n".join(unit.source_text for unit in plan.units)
    assert "EARLY_BUG_SENTINEL" in combined
    assert "LATE_BUG_SENTINEL" in combined
    assert all("HugeMethod#process" in unit.changed_symbol_ids for unit in plan.units)


def test_twenty_changed_files_have_complete_hunk_assignment() -> None:
    files = [
        ChangedFile(
            f"src/File{index}.java",
            f"@@ -1,1 +1,1 @@\n-old{index}\n+new{index}",
        )
        for index in range(20)
    ]
    sources = {item.filename: f"new{index}\n" for index, item in enumerate(files)}

    plan = plan_context_units(files, source_file_contents=sources, related_context={})

    assert plan.diff_assignment_rate == 1.0
    assert len(plan.assigned_hunk_ids) == 20
    assert len(set(plan.assigned_hunk_ids)) == 20
    assert not plan.unresolved


def test_missing_full_source_uses_audited_patch_fallback() -> None:
    changed = ChangedFile("src/Fallback.java", "@@ -9,1 +10,1 @@\n-old\n+new")

    plan = plan_context_units([changed], source_file_contents={}, related_context={})

    assert plan.diff_assignment_rate == 1.0
    assert plan.units[0].fallback_reason == "no_full_source"
    assert "+new" in plan.units[0].source_text


def test_expert_llm_uses_context_unit_prompt() -> None:
    changed = ChangedFile("src/A.java", "@@ -1,1 +1,1 @@\n-old\n+new")
    unit = plan_context_units(
        [changed],
        source_file_contents={"src/A.java": "new\n"},
        related_context={},
    ).units[0]

    class Recorder:
        def __init__(self):
            self.prompt = ""

        def llm_call(self, _span, _provider, _model, prompt, *_args):
            self.prompt = prompt

        def event(self, *_args):
            return None

    recorder = Recorder()
    original = llm_client.candidate_providers
    llm_client.candidate_providers = lambda *_args, **_kwargs: []
    try:
        llm_client.call_llm({}, recorder, "span", {**_agent(), "context_unit": unit}, [changed], "")
    finally:
        llm_client.candidate_providers = original

    payload = json.loads(recorder.prompt)
    assert payload["structured_diff"]["format"] == "context_units_v2"


def test_expert_batch_executes_every_context_unit() -> None:
    files = [
        ChangedFile("src/A.java", "@@ -1,1 +1,1 @@\n-old\n+new"),
        ChangedFile("src/B.java", "@@ -1,1 +1,1 @@\n-old\n+new"),
    ]
    plan = plan_context_units(
        files,
        source_file_contents={"src/A.java": "new\n", "src/B.java": "new\n"},
        related_context={},
    )
    seen: list[str] = []

    def fake_call(_config, _recorder, _span, agent, _files, _skill):
        seen.append(agent["context_unit"].unit_id)
        return [{"title": agent["context_unit"].unit_id}]

    items, executed, unresolved = call_llm_for_context_units(
        call_llm=fake_call,
        config={},
        recorder=None,
        span="span",
        agent=_agent(),
        files=files,
        skill_summary="",
        context_units=list(plan.units),
        budget_tracker=None,
    )

    assert len(items) == 2
    assert sorted(seen) == sorted(unit.unit_id for unit in plan.units)
    assert sorted(executed) == sorted(seen)
    assert unresolved == []


def test_context_unit_includes_cross_file_semantic_dependencies() -> None:
    changed = ChangedFile("src/A.java", "@@ -1,1 +1,1 @@\n-old\n+new")
    target = SemanticNode("target", "function", "target", "src/A.java", 1, 1)
    caller = SemanticNode("caller", "function", "run", "src/B.java", 1, 3)
    graph = SemanticGraph(
        nodes=(target, caller),
        edges=(SemanticEdge("caller", "target", "calls", "syntax", "tree_sitter_local_call"),),
        status="full",
        degradations=(),
    )

    plan = plan_context_units(
        [changed],
        source_file_contents={"src/A.java": "new\n"},
        related_context={},
        semantic_graph=graph,
        source_loader=lambda path: "void run() { target(); }\n" if path == "src/B.java" else "",
    )

    assert plan.units[0].dependencies[0].source.file_path == "src/B.java"
    assert plan.units[0].dependencies[0].confidence == "syntax"
    prompt, _ = build_context_unit_prompt(_agent(), plan.units[0], "")
    assert "target();" in prompt

    def fake_call(_config, _recorder, _span, _agent_config, _files, _skill):
        return [
            {
                "title": "cross-file issue",
                "semantic_evidence": [
                    {"symbol_id": "caller", "relation": "calls", "file_path": "src/B.java"}
                ],
            }
        ]

    findings, _executed, _unresolved = call_llm_for_context_units(
        call_llm=fake_call,
        config={},
        recorder=None,
        span="span",
        agent=_agent(),
        files=[changed],
        skill_summary="",
        context_units=list(plan.units),
    )
    assert findings[0]["semantic_paths"][0]["complete"] is True
    assert findings[0]["semantic_paths"][0]["edges"][0]["confidence"] == "syntax"


def test_model_cannot_invent_a_trusted_semantic_edge() -> None:
    changed = ChangedFile("src/A.java", "@@ -1,1 +1,1 @@\n-old\n+new")
    plan = plan_context_units(
        [changed],
        source_file_contents={"src/A.java": "new\n"},
        related_context={},
    )

    def fake_call(_config, _recorder, _span, _agent_config, _files, _skill):
        return [{"semantic_evidence": [{"symbol_id": "invented", "relation": "calls", "file_path": "src/X.java"}]}]

    findings, _executed, _unresolved = call_llm_for_context_units(
        call_llm=fake_call,
        config={},
        recorder=None,
        span="span",
        agent=_agent(),
        files=[changed],
        skill_summary="",
        context_units=list(plan.units),
    )
    assert findings[0]["semantic_paths"] == []
    assert "semantic_evidence_unresolved" in findings[0]["unresolved_context"]


if __name__ == "__main__":
    test_large_file_late_hunk_is_present_in_executable_context()
    test_distant_hunks_in_one_oversized_symbol_are_not_lost_by_center_crop()
    test_twenty_changed_files_have_complete_hunk_assignment()
    test_missing_full_source_uses_audited_patch_fallback()
    test_expert_llm_uses_context_unit_prompt()
    test_expert_batch_executes_every_context_unit()
    test_context_unit_includes_cross_file_semantic_dependencies()
    test_model_cannot_invent_a_trusted_semantic_edge()
    print("context planner tests passed")
