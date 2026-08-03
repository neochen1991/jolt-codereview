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
from prompts import builder as prompt_builder  # noqa: E402
from prompts.builder import build_context_unit_prompt, build_context_units_prompt  # noqa: E402


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


def test_context_unit_records_deterministic_change_intent() -> None:
    changed = ChangedFile(
        "src/main/java/com/acme/RefundService.java",
        "@@ -10,1 +10,2 @@\n process(refund);\n+logger.info(\"refund processed {}\", refund.id());",
    )

    unit = plan_context_units(
        [changed],
        source_file_contents={changed.filename: "process(refund);\nlogger.info(\"refund processed {}\", refund.id());\n"},
        related_context={},
    ).units[0]

    assert unit.change_intent.labels == ("logging_only",), unit
    assert unit.to_prompt_item()["change_intent"]["semantic_delta"] == "behavior_preserving"


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

        def llm_call(self, _span, _provider, _model, prompt, *_args, **_kwargs):
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
    calls = 0

    def fake_call(_config, _recorder, _span, agent, _files, _skill):
        nonlocal calls
        calls += 1
        batch = list(agent["context_units"])
        seen.extend(unit.unit_id for unit in batch)
        return [
            {"title": unit.unit_id, "file_path": unit.primary_source.file_path, "line_start": unit.primary_source.line_start}
            for unit in batch
        ]

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
    assert calls == 1
    assert sorted(seen) == sorted(unit.unit_id for unit in plan.units)
    assert sorted(executed) == sorted(seen)
    assert unresolved == []


def test_empty_scoped_context_does_not_fall_back_to_full_file_review() -> None:
    calls = 0

    def fake_call(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return [{"title": "must not execute"}]

    findings, executed, unresolved = call_llm_for_context_units(
        call_llm=fake_call,
        config={},
        recorder=object(),
        span="span",
        agent=_agent(),
        files=[ChangedFile("src/A.java", "@@ -1,1 +1,1 @@\n-old\n+new")],
        skill_summary="# complete skill",
        context_units=[],
    )

    assert calls == 0
    assert findings == []
    assert executed == []
    assert unresolved == [{"unit_id": "", "reason": "no_relevant_context_units"}]


def test_context_units_are_chunked_to_control_real_review_call_volume() -> None:
    files = [
        ChangedFile(f"src/File{index}.java", "@@ -1,1 +1,1 @@\n-old\n+new")
        for index in range(13)
    ]
    plan = plan_context_units(
        files,
        source_file_contents={item.filename: "new\n" for item in files},
        related_context={},
    )
    batch_sizes: list[int] = []

    def fake_call(_config, _recorder, _span, agent, _files, _skill):
        batch = list(agent["context_units"])
        batch_sizes.append(len(batch))
        return []

    _items, executed, unresolved = call_llm_for_context_units(
        call_llm=fake_call,
        config={"review_quality": {"context_units_per_llm_call": 6}},
        recorder=None,
        span="span",
        agent=_agent(),
        files=files,
        skill_summary="",
        context_units=list(plan.units),
        budget_tracker=None,
    )

    assert batch_sizes == [6, 6, 1]
    assert sorted(executed) == sorted(unit.unit_id for unit in plan.units)
    assert unresolved == []


def test_expert_batch_stops_before_next_context_unit_when_review_is_cancelled() -> None:
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
    checks = 0

    def ensure_active() -> None:
        nonlocal checks
        checks += 1
        if checks > 1:
            raise RuntimeError("review_cancelled")

    def fake_call(_config, _recorder, _span, agent, _files, _skill):
        seen.extend(unit.unit_id for unit in agent["context_units"])
        return []

    try:
        call_llm_for_context_units(
            call_llm=fake_call,
            config={"review_quality": {"context_units_per_llm_call": 1}},
            recorder=None,
            span="span",
            agent=_agent(),
            files=files,
            skill_summary="",
            context_units=list(plan.units),
            ensure_active=ensure_active,
        )
        raise AssertionError("cancelled review should abort the remaining context units")
    except RuntimeError as exc:
        assert str(exc) == "review_cancelled"

    assert len(seen) == 1


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


def test_validated_semantic_dependency_synthesizes_evidence_path() -> None:
    changed = ChangedFile(
        "src/main/java/com/acme/payment/service/PaymentQueryService.java",
        "@@ -22,1 +22,1 @@\n-old\n+String sql = \"select * from payments where user_id='\" + userId + \"'\";",
    )
    service = SemanticNode(
        "service_search",
        "function",
        "searchByUser",
        "src/main/java/com/acme/payment/service/PaymentQueryService.java",
        20,
        26,
    )
    controller = SemanticNode(
        "controller_search",
        "function",
        "search",
        "src/main/java/com/acme/payment/api/PaymentAdminController.java",
        18,
        24,
    )
    graph = SemanticGraph(
        nodes=(service, controller),
        edges=(SemanticEdge("controller_search", "service_search", "calls", "syntax", "tree_sitter_receiver_type"),),
        status="full",
        degradations=(),
    )
    plan = plan_context_units(
        [changed],
        source_file_contents={
            changed.filename: "class PaymentQueryService {\n  java.util.List searchByUser(String userId) {\n    String sql = \"select * from payments where user_id='\" + userId + \"'\";\n    return jdbc.queryForList(sql);\n  }\n}\n",
            "src/main/java/com/acme/payment/api/PaymentAdminController.java": "class PaymentAdminController {\n  Map search(Map payload) {\n    return paymentQueryService.searchByUser(String.valueOf(payload.get(\"userId\")));\n  }\n}\n",
        },
        related_context={},
        semantic_graph=graph,
        source_loader=lambda path: "class PaymentAdminController {\n  Map search(Map payload) {\n    return paymentQueryService.searchByUser(String.valueOf(payload.get(\"userId\")));\n  }\n}\n"
        if path == "src/main/java/com/acme/payment/api/PaymentAdminController.java"
        else "",
    )

    assert plan.units[0].dependencies

    def fake_call(_config, _recorder, _span, _agent_config, _files, _skill):
        return [
            {
                "title": "SQL 拼接漏洞：用户输入直接拼接入 SQL 语句",
                "file_path": changed.filename,
                "line_start": 22,
                "line_end": 22,
                "evidence_scope": "cross_file",
                "semantic_evidence": [
                    {
                        "symbol_id": "controller_search",
                        "relation": "calls",
                        "file_path": "src/main/java/com/acme/payment/api/PaymentAdminController.java",
                    }
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
    assert len(findings[0]["evidence_path"]) >= 2
    assert findings[0]["evidence_path"][0]["file_path"] == changed.filename
    assert findings[0]["evidence_path"][1]["file_path"] == "src/main/java/com/acme/payment/api/PaymentAdminController.java"


def test_trusted_dependency_synthesizes_evidence_path_without_model_claim() -> None:
    changed = ChangedFile(
        "src/main/java/com/acme/payment/service/PaymentQueryService.java",
        "@@ -22,1 +22,1 @@\n-old\n+String sql = \"select * from payments where user_id='\" + userId + \"'\";",
    )
    service = SemanticNode(
        "service_search",
        "function",
        "searchByUser",
        "src/main/java/com/acme/payment/service/PaymentQueryService.java",
        20,
        26,
    )
    controller = SemanticNode(
        "controller_search",
        "function",
        "search",
        "src/main/java/com/acme/payment/api/PaymentAdminController.java",
        18,
        24,
    )
    graph = SemanticGraph(
        nodes=(service, controller),
        edges=(SemanticEdge("controller_search", "service_search", "calls", "syntax", "tree_sitter_receiver_type"),),
        status="full",
        degradations=(),
    )
    plan = plan_context_units(
        [changed],
        source_file_contents={changed.filename: "class PaymentQueryService { List searchByUser(String userId) { return jdbc.query(sql); } }"},
        related_context={},
        semantic_graph=graph,
        source_loader=lambda path: "class PaymentAdminController { Map search(Map payload) { return paymentQueryService.searchByUser(String.valueOf(payload.get(\"userId\"))); } }"
        if path == "src/main/java/com/acme/payment/api/PaymentAdminController.java"
        else "",
    )

    def fake_call(_config, _recorder, _span, _agent_config, _files, _skill):
        return [
            {
                "title": "SQL 拼接漏洞：用户输入直接拼接入 SQL 语句",
                "file_path": changed.filename,
                "line_start": 22,
                "line_end": 22,
                "evidence_scope": "cross_file",
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
    assert findings[0]["semantic_paths"][0]["edges"][0]["resolver"] == "context_planner_fallback"
    assert len(findings[0]["evidence_path"]) >= 2
    assert findings[0]["evidence_path"][1]["file_path"] == "src/main/java/com/acme/payment/api/PaymentAdminController.java"


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


def test_context_unit_prompt_scopes_related_context_to_current_change_graph() -> None:
    context_unit = {
        "unit_id": "ctx_1",
        "hunk_ids": ["hunk_1"],
        "file_path": "src/Changed.java",
        "line_start": 10,
        "line_end": 20,
        "changed_symbol_ids": ["Changed#run"],
        "source_text": "10: void run() { caller(); }",
        "patch_text": "@@ -10,1 +10,1 @@\n+caller();",
        "dependencies": [
            {
                "relation": "calls",
                "symbol_id": "Caller#call",
                "file_path": "src/Caller.java",
                "line_start": 3,
                "line_end": 5,
                "confidence": "syntax",
                "source_text": "3: void call() {}",
            }
        ],
        "skill_checkpoint_ids": [],
        "context_hash": "hash-1",
    }
    agent = {
        **_agent(),
        "related_context": {
            "format": "related_context_v2",
            "status": "resolved",
            "changed_symbols": [
                {"symbol_id": "Changed#run", "name": "run", "definition_file": "src/Changed.java"},
                {"symbol_id": "Unrelated#run", "name": "unrelated", "definition_file": "src/Unrelated.java", "definition_snippet": "UNRELATED_SENTINEL"},
            ],
            "modified_symbols": [
                {"symbol_id": "Caller#call", "name": "call", "definition_file": "src/Caller.java", "definition_snippet": "CALLER_SENTINEL"},
                {"symbol_id": "Other#call", "name": "other", "definition_file": "src/Other.java", "definition_snippet": "OTHER_SENTINEL"},
            ],
            "related_tests": ["src/ChangedTest.java", "src/OtherTest.java"],
        },
    }

    prompt, _ = build_context_units_prompt(agent, [context_unit], "")
    payload = json.loads(prompt)

    assert payload["related_context"]["status"] == "scoped_to_context_units"
    assert "CALLER_SENTINEL" in prompt
    assert "UNRELATED_SENTINEL" not in prompt
    assert "OTHER_SENTINEL" not in prompt
    assert "src/OtherTest.java" not in prompt
    assert payload["input_budget_policy"]["symbols"].startswith("只发送当前 ContextUnit 批次相关")


def test_context_unit_prompt_limits_dependency_source_payload() -> None:
    context_unit = {
        "unit_id": "ctx_1",
        "hunk_ids": ["hunk_1"],
        "file_path": "src/Changed.java",
        "line_start": 1,
        "line_end": 1,
        "changed_symbol_ids": ["Changed#run"],
        "source_text": "1: changed",
        "patch_text": "@@ -1,1 +1,1 @@\n+changed",
        "dependencies": [
            {
                "relation": "calls",
                "symbol_id": f"Dep{index}",
                "file_path": f"src/Dep{index}.java",
                "line_start": 1,
                "line_end": 1,
                "confidence": "syntax",
                "source_text": f"DEPENDENCY_SENTINEL_{index}",
            }
            for index in range(10)
        ],
        "skill_checkpoint_ids": [],
        "context_hash": "hash-1",
    }

    prompt, _ = build_context_units_prompt(_agent(), [context_unit], "")
    payload = json.loads(prompt)
    dependencies = payload["structured_diff"]["items"][0]["dependencies"]

    assert len(dependencies) == 8
    assert "DEPENDENCY_SENTINEL_7" in prompt
    assert "DEPENDENCY_SENTINEL_8" not in prompt
    assert payload["structured_diff"]["items"][0]["dependency_scope_note"]


def test_context_prompt_has_stable_complete_skill_prefix_and_dynamic_batch_body() -> None:
    build_parts = getattr(prompt_builder, "build_context_units_prompt_parts", None)
    assert callable(build_parts), "context prompt must expose stable and dynamic request parts"
    context_unit = {
        "unit_id": "ctx_1",
        "hunk_ids": ["hunk_1"],
        "file_path": "src/Changed.java",
        "line_start": 1,
        "line_end": 1,
        "changed_symbol_ids": ["Changed#run"],
        "source_text": "1: changed",
        "patch_text": "@@ -1,1 +1,1 @@\n+changed",
        "dependencies": [],
        "skill_checkpoint_ids": [],
        "context_hash": "hash-1",
    }
    skill = "# COMPLETE SKILL\n\nAll standards and counterexamples must remain available."
    agent_a = {
        **_agent(),
        "bound_rules": [{"rule_id": "RULE-A", "required_evidence": "Changed#run"}],
        "bound_rule_batch": {"rule_ids": ["RULE-A"]},
    }
    agent_b = {
        **_agent(),
        "bound_rules": [{"rule_id": "RULE-B", "required_evidence": "Changed#run"}],
        "bound_rule_batch": {"rule_ids": ["RULE-B"]},
    }

    _prompt_a, safety_a = build_parts(agent_a, [context_unit], skill)
    _prompt_b, safety_b = build_parts(agent_b, [context_unit], skill)

    assert safety_a["stable_prompt"] == safety_b["stable_prompt"]
    assert safety_a["dynamic_prompt"] != safety_b["dynamic_prompt"]
    stable_payload = json.loads(safety_a["stable_prompt"])
    assert stable_payload["review_rules"]["dedicated_markdown_standard"] == skill
    assert "RULE-A" not in safety_a["stable_prompt"]
    assert "RULE-A" in safety_a["dynamic_prompt"]
    assert safety_a["stable_prefix_hash"] == safety_b["stable_prefix_hash"]


def test_input_composition_reports_all_prompt_token_categories() -> None:
    compose = getattr(llm_client, "input_composition_for_prompt", None)
    assert callable(compose), "expert client must expose deterministic input composition"
    context_unit = {
        "unit_id": "ctx_1",
        "hunk_ids": ["hunk_1"],
        "file_path": "src/Changed.java",
        "line_start": 1,
        "line_end": 2,
        "changed_symbol_ids": ["Changed#run"],
        "source_text": "1: class Changed {\n2: void run() {}\n}",
        "patch_text": "@@ -1,1 +1,2 @@\n+void run() {}",
        "dependencies": [
            {
                "relation": "calls",
                "symbol_id": "Caller#call",
                "file_path": "src/Caller.java",
                "line_start": 3,
                "line_end": 3,
                "confidence": "typed",
                "source_text": "3: changed.run();",
            }
        ],
        "skill_checkpoint_ids": [],
        "context_hash": "hash-1",
    }
    agent = {
        **_agent(),
        "bound_rules": [{"rule_id": "RULE-A", "required_evidence": "Changed#run"}],
        "bound_rule_batch": {"rule_ids": ["RULE-A"]},
        "tool_observations": [{"rule_id": "RULE-A", "file_path": "src/Changed.java", "evidence": "run"}],
    }
    prompt, metadata = prompt_builder.build_context_units_prompt_parts(agent, [context_unit], "# COMPLETE SKILL")

    composition = compose(prompt, metadata)

    required = {
        "source_tokens",
        "dependency_tokens",
        "skill_tokens",
        "tool_observation_tokens",
        "fixed_instruction_tokens",
        "patch_tokens",
        "other_dynamic_tokens",
        "estimated_input_tokens",
        "stable_prefix_hash",
    }
    assert required <= set(composition)
    assert all(composition[key] > 0 for key in required - {"stable_prefix_hash", "other_dynamic_tokens"})
    assert composition["estimated_input_tokens"] == sum(
        composition[key]
        for key in (
            "source_tokens",
            "dependency_tokens",
            "skill_tokens",
            "tool_observation_tokens",
            "fixed_instruction_tokens",
            "patch_tokens",
            "other_dynamic_tokens",
        )
    )


def test_expert_llm_logs_input_composition_when_provider_is_unavailable() -> None:
    changed = ChangedFile("src/A.java", "@@ -1,1 +1,1 @@\n-old\n+new")
    unit = plan_context_units(
        [changed],
        source_file_contents={"src/A.java": "password=supersecret123\n"},
        related_context={},
    ).units[0]

    class Recorder:
        def __init__(self):
            self.events = []
            self.composition = None

        def llm_call(self, *_args, **kwargs):
            self.composition = kwargs.get("input_composition")

        def event(self, _span, event_type, _summary, payload=None):
            self.events.append((event_type, payload or {}))

    recorder = Recorder()
    original = llm_client.candidate_providers
    llm_client.candidate_providers = lambda *_args, **_kwargs: []
    try:
        llm_client.call_llm({}, recorder, "span", {**_agent(), "context_unit": unit}, [changed], "# COMPLETE SKILL")
    finally:
        llm_client.candidate_providers = original

    assert recorder.composition is not None
    assert recorder.composition["skill_tokens"] > 0
    assert any(event_type == "llm_input_composition" for event_type, _payload in recorder.events)
    redaction_payloads = [payload for event_type, payload in recorder.events if event_type == "redaction_applied"]
    assert redaction_payloads
    assert all("stable_prompt" not in payload and "dynamic_prompt" not in payload for payload in redaction_payloads)


if __name__ == "__main__":
    test_large_file_late_hunk_is_present_in_executable_context()
    test_distant_hunks_in_one_oversized_symbol_are_not_lost_by_center_crop()
    test_twenty_changed_files_have_complete_hunk_assignment()
    test_missing_full_source_uses_audited_patch_fallback()
    test_context_unit_records_deterministic_change_intent()
    test_expert_llm_uses_context_unit_prompt()
    test_expert_batch_executes_every_context_unit()
    test_empty_scoped_context_does_not_fall_back_to_full_file_review()
    test_context_units_are_chunked_to_control_real_review_call_volume()
    test_expert_batch_stops_before_next_context_unit_when_review_is_cancelled()
    test_context_unit_includes_cross_file_semantic_dependencies()
    test_validated_semantic_dependency_synthesizes_evidence_path()
    test_model_cannot_invent_a_trusted_semantic_edge()
    test_context_unit_prompt_scopes_related_context_to_current_change_graph()
    test_context_unit_prompt_limits_dependency_source_payload()
    test_context_prompt_has_stable_complete_skill_prefix_and_dynamic_batch_body()
    test_input_composition_reports_all_prompt_token_categories()
    test_expert_llm_logs_input_composition_when_provider_is_unavailable()
    print("context planner tests passed")
