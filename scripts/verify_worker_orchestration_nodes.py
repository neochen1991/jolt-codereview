from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from budget import BudgetTracker
from llm.client import collect_openai_sse_response, parse_llm_findings, parse_openai_response_text
from llm_router import candidate_providers
from review_runtime import (
    ChangedFile,
    Recorder,
    parse_semgrep_findings,
    prepare_source_worktree,
    route_agents,
    run_static_command,
    static_tool_enabled,
    static_tool_timeout_seconds,
    tree_sitter_graph_options,
    source_content_candidate_count,
    source_worktree_mode,
)
from orchestration.nodes.detect_conflicts import detect_conflicts
from orchestration.nodes.choose_effort import budget_for_effort
from orchestration.nodes.judge_findings import (
    apply_debate_verdicts,
    filter_to_diff_introduced_findings,
    filter_tool_observations_to_added_lines,
    judge_candidate_findings,
    make_judge_findings_node,
    match_tool_observations_for_finding,
    promote_tool_observations,
)
from orchestration.nodes.run_targeted_debate import run_targeted_debate
from orchestration.nodes.summarize_pr import make_summarize_pr_node
from orchestration.nodes.verify_findings import verify_candidate_findings
from orchestration.state import EXECUTED_GRAPH_NODE_KEYS, TARGET_GRAPH_NODE_KEYS
from orchestration.deepagents_runner import OpenAICompatibleToolChatModel
from prompts.builder import build_prompt
from tools.registry import findings_to_observations
from tools.tree_sitter_tool import build_diff_graph
from langchain_core.messages import HumanMessage

node_dir = ROOT / "worker" / "orchestration" / "nodes"
required_node_files = [
    "fetch_mr.py",
    "choose_effort.py",
    "prescan.py",
    "build_context.py",
    "route_agents.py",
    "run_experts.py",
    "verify_findings.py",
    "detect_conflicts.py",
    "run_targeted_debate.py",
    "judge_findings.py",
    "summarize_pr.py",
    "finalize.py",
]
missing_node_files = [name for name in required_node_files if not (node_dir / name).exists()]
assert not missing_node_files, missing_node_files

runtime_text = (ROOT / "worker" / "review_runtime.py").read_text("utf-8")
graph_text = (ROOT / "worker" / "orchestration" / "graph.py").read_text("utf-8")
llm_client_text = (ROOT / "worker" / "llm" / "client.py").read_text("utf-8")
deepagents_text = (ROOT / "worker" / "orchestration" / "deepagents_runner.py").read_text("utf-8")
targeted_debate_text = (ROOT / "worker" / "orchestration" / "nodes" / "run_targeted_debate.py").read_text("utf-8")
assert "def fetch_node(" not in runtime_text
assert "def choose_effort_node(" not in runtime_text
assert "def prescan_node(" not in runtime_text
assert "def route_agents_node(" not in runtime_text
assert "def expert_agents_node(" not in runtime_text
assert "def run_experts_node(" not in runtime_text
assert "def verify_findings_node(" not in runtime_text
assert "def detect_conflicts_node(" not in runtime_text
assert "def run_targeted_debate_node(" not in runtime_text
assert "def judge_findings_node(" not in runtime_text
assert "def summarize_pr_node(" not in runtime_text
assert "def finalize_node(" not in runtime_text
assert "def ensure_worker_schema(" in runtime_text
for trace_column in ["tool_provenance_json", "source_observations_json", "quality_trace_json"]:
    assert trace_column in runtime_text, trace_column
for forbidden_vcs_direct in [
    "def github_token(",
    "def codehub_token(",
    "def fetch_github_changed_files(",
    "def fetch_codehub_changed_files(",
    "api.github.com",
    "CODEHUB_TOKEN",
]:
    assert forbidden_vcs_direct not in runtime_text, forbidden_vcs_direct
assert "fetch_changed_files_via_backend" in runtime_text
assert "/vcs/" in runtime_text
assert "deterministic_fallback" not in graph_text
assert "langgraph_fallback" not in graph_text
assert "LangGraph is required in production review orchestration" in graph_text
assert EXECUTED_GRAPH_NODE_KEYS == TARGET_GRAPH_NODE_KEYS
assert "timeout=30" not in llm_client_text
assert "llm_request_timeout_seconds" in llm_client_text
assert "min(600" in llm_client_text
assert "llm_stream_enabled" in llm_client_text
assert "collect_openai_sse_response" in llm_client_text
assert "request_timeout_seconds" in deepagents_text
assert "enable_stream" in deepagents_text
assert "collect_openai_sse_response(response, started)" in deepagents_text
assert "def read_file(path: str)" in deepagents_text
assert "def read_diff_patch(path: str)" in deepagents_text
assert "min(max_tool_calls, 16)" in deepagents_text
assert "trace_callback" in deepagents_text
assert "timeout_seconds=timeout_seconds" in targeted_debate_text
assert "stream=stream_enabled" in targeted_debate_text
assert "llm_request_timeout_seconds" in runtime_text
assert "llm_stream_enabled" in runtime_text
assert "http_json as llm_http_json" in runtime_text
assert "response = llm_http_json(" in runtime_text
assert static_tool_timeout_seconds({}, "semgrep") == 120
assert static_tool_timeout_seconds({}, "checkstyle") == 120
assert static_tool_timeout_seconds({}, "dependency-check") == 180
assert tree_sitter_graph_options({}, [ChangedFile("src/App.java", "modified", 1, 0, 1, "+class App {}")])["timeout_seconds"] == 120

sse_response = collect_openai_sse_response(
    [
        'data: {"id":"chatcmpl-test","choices":[{"delta":{"content":"中文"},"finish_reason":null}]}\n'.encode("utf-8"),
        'data: {"choices":[{"delta":{"content":"回答","tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"inspect_agent_rules","arguments":"{}"}}]},"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":12,"completion_tokens":3}}\n'.encode("utf-8"),
        b"data: [DONE]\n",
    ],
    time.time(),
)
assert sse_response["choices"][0]["message"]["content"] == "中文回答"
assert sse_response["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "inspect_agent_rules"
assert sse_response["_jolt_stream"]["chunk_count"] == 2
mislabeled_sse_response = parse_openai_response_text(
    'data: {"id":"chatcmpl-mislabel","choices":[{"delta":{"content":"仍然"},"finish_reason":null}]}\n'
    'data: {"choices":[{"delta":{"content":"解析"},"finish_reason":"stop"}]}\n'
    "data: [DONE]\n",
    time.time(),
)
assert mislabeled_sse_response["choices"][0]["message"]["content"] == "仍然解析"
assert mislabeled_sse_response["_jolt_stream"]["chunk_count"] == 2

deepagent_llm_traces = []

class FakeDeepAgentResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(
            {
                "id": "deep_req_1",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "上下文摘要"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            },
            ensure_ascii=False,
        ).encode("utf-8")

original_urlopen = urllib.request.urlopen
urllib.request.urlopen = lambda *_args, **_kwargs: FakeDeepAgentResponse()
try:
    traced_model = OpenAICompatibleToolChatModel(
        provider="test-provider",
        model_name="test-model",
        base_url="http://llm.local",
        api_key="secret",
        trace_callback=lambda fields: deepagent_llm_traces.append(fields),
    )
    traced_model._generate([HumanMessage(content="读取规则并检视 diff")])
finally:
    urllib.request.urlopen = original_urlopen
assert deepagent_llm_traces, "DeepAgents model must emit LLM trace records"
assert deepagent_llm_traces[0]["request_messages"][0]["content"] == "读取规则并检视 diff", deepagent_llm_traces
assert "上下文摘要" in deepagent_llm_traces[0]["response_text"], deepagent_llm_traces
assert "semgrep_config_values" in runtime_text
assert "static.semgrep.aggregate" in runtime_text
assert "output_path.parent.mkdir(parents=True, exist_ok=True)" in runtime_text


class PromptFile:
    def __init__(self, filename: str, patch: str, additions: int = 1, deletions: int = 0, status: str = "modified"):
        self.filename = filename
        self.patch = patch
        self.additions = additions
        self.deletions = deletions
        self.status = status


prompt_files = [
    PromptFile(f"src/main/java/com/acme/payment/File{i}.java", "@@ -1 +1 @@\n" + ("+BigDecimal amount = input;\n" * 400), 400)
    for i in range(16)
] + [
    PromptFile("src/test/java/com/acme/payment/PaymentServiceTest.java", "@@ -1 +1 @@\n+assertThat(result).isTrue();\n", 2)
]
prompt, _safety = build_prompt(
    {
        "agent_id": "test_agent",
        "display_name": "测试专家",
        "applies_to": {
            "persona": "测试专家",
            "exclusive_scope": "测试覆盖、断言质量、回归用例",
            "review_scope": "test junit coverage",
        },
        "tool_observations": [{"message": "x" * 2000} for _ in range(80)],
        "bound_rules": [{"rule_id": f"R-{i}", "content": "x" * 2000} for i in range(80)],
    },
    prompt_files,
    "x" * 20000,
)
prompt_payload = json.loads(prompt)
prompt_items = prompt_payload["structured_diff"]["items"]
assert len(prompt_items) <= 12, len(prompt_items)
assert prompt_items[0]["file"] == "src/test/java/com/acme/payment/PaymentServiceTest.java", prompt_items[0]
assert len(prompt) < 60000, len(prompt)

java_ddd_route_agents = [
    {
        "agent_id": "ddd_agent",
        "display_name": "DDD Design Agent",
        "applies_to": {
            "persona": "DDD 设计专家",
            "exclusive_scope": "ddd_design",
            "review_scope": "领域建模、聚合、应用服务、仓储、领域事件和上下文边界",
            "languages": ["java"],
            "paths": ["src/main/java/**/domain/**", "src/main/java/**/application/**", "src/main/java/**/service/**", "src/main/java/**/repository/**"],
            "triggers": ["domain", "aggregate", "application service", "bounded context", "domain event"],
        },
    },
    {
        "agent_id": "backend_agent",
        "display_name": "Backend Agent",
        "applies_to": {
            "persona": "后端专家",
            "exclusive_scope": "backend",
            "review_scope": "API、服务编排和事务",
            "languages": ["java"],
            "paths": ["src/main/java/**"],
            "triggers": ["transaction", "service", "exception"],
        },
    },
    {
        "agent_id": "coding_agent",
        "display_name": "Coding Agent",
        "applies_to": {
            "persona": "通用编码专家",
            "exclusive_scope": "general_coding",
            "review_scope": "实现正确性",
            "languages": ["java"],
            "paths": ["src/main/java/**"],
            "triggers": ["null", "exception", "state"],
        },
    },
    {
        "agent_id": "security_agent",
        "display_name": "Security Agent",
        "applies_to": {
            "persona": "安全专家",
            "exclusive_scope": "security",
            "review_scope": "安全漏洞",
            "languages": ["java"],
            "paths": ["src/main/java/**"],
            "triggers": ["auth", "token"],
        },
    },
    {
        "agent_id": "test_agent",
        "display_name": "Test Agent",
        "applies_to": {
            "persona": "测试专家",
            "exclusive_scope": "test_coverage",
            "review_scope": "测试覆盖",
            "languages": ["java"],
            "paths": ["src/test/java/**"],
            "triggers": ["test", "assert"],
        },
    },
]
java_ddd_files = [
    ChangedFile(
        "src/main/java/com/acme/payment/application/PaymentDddApplicationService.java",
        "modified",
        7,
        0,
        7,
        "@@ -20,0 +21,7 @@\n"
        "+public void forceTransition(String paymentId, String nextStatus, String merchantId) {\n"
        "+    PaymentOrder order = paymentMapper.find(paymentId);\n"
        "+    order.setStatus(PaymentStatus.valueOf(nextStatus));\n"
        "+    order.setMerchantId(merchantId);\n"
        "+    paymentMapper.save(order);\n"
        "+}\n",
    )
]
java_ddd_selected = route_agents(java_ddd_route_agents, java_ddd_files, "standard")
java_ddd_selected_ids = [agent["agent_id"] for agent in java_ddd_selected]
assert "ddd_agent" in java_ddd_selected_ids, java_ddd_selected_ids

partial_findings = parse_llm_findings(
    "security_agent",
    """
[
  {
    "severity": "high",
    "confidence": "high",
    "file_path": "src/main/java/com/acme/payment/File1.java",
    "line_start": 12,
    "line_end": 12,
    "title": "完整对象应被保留",
    "problem_description": "模型输出被截断时，完整 JSON 对象不能整批丢失。",
    "recommendation": "保留完整对象，丢弃未闭合对象。",
    "suggested_code": "return safeValue;",
    "evidence": "line 12",
    "covered_rules": ["SEC-AUTHZ-002"]
  },
  {
    "severity": "medium",
    "confidence": "medium",
    "file_path": "src/main/java/com/acme/payment/File2.java",
    "line_start":
""",
    [
        ChangedFile("src/main/java/com/acme/payment/File1.java", "modified", 1, 0, 1, "@@ -12 +12 @@\n+return value;"),
        ChangedFile("src/main/java/com/acme/payment/File2.java", "modified", 1, 0, 1, "@@ -1 +1 @@\n+x"),
    ],
)
assert len(partial_findings) == 1, partial_findings
assert partial_findings[0]["confidence"] == 0.9, partial_findings


with tempfile.TemporaryDirectory() as tmp:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE review_trace_events (
            id TEXT PRIMARY KEY,
            run_id TEXT,
            span_id TEXT,
            event_type TEXT,
            title TEXT,
            detail TEXT,
            metadata_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE tool_call_records (
            id TEXT PRIMARY KEY,
            span_id TEXT,
            tool_name TEXT,
            tool_version TEXT,
            args_summary TEXT,
            input_ref_json TEXT,
            output_summary TEXT,
            output_ref_json TEXT,
            duration_ms INTEGER,
            status TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            ended_at TEXT
        )
        """
    )
    recorder = Recorder(conn, "run_verify")
    out = Path(tmp) / "nested" / "tool" / "stdout.json"
    result = run_static_command(
        recorder,
        "span_verify",
        sys.executable,
        ["-c", "import sys; sys.stdout.write('{\"ok\": true}')"],
        out,
        {0},
        10,
    )
    assert result["status"] == "completed", result
    assert out.exists(), out

    marker = Path(tmp) / "static_tool_child_survived.txt"
    result = run_static_command(
        recorder,
        "span_verify",
        sys.executable,
        [
            "-c",
            (
                "import subprocess, sys, time; "
                f"subprocess.Popen([sys.executable, '-c', \"import pathlib, time; time.sleep(1.2); pathlib.Path(r'{marker}').write_text('alive')\"]); "
                "time.sleep(20)"
            ),
        ],
        None,
        {0},
        1,
    )
    time.sleep(1.8)
    assert result["status"] == "timeout", result
    assert not marker.exists(), "timed-out static tool left a child process running"


findings = [
    {
        "agent_id": "security_agent",
        "severity": "high",
        "confidence": 0.91,
        "dedupe_hash": "hash_security",
        "file_path": "backend/api/project.py",
        "line_start": 88,
        "title": "missing authorization",
        "problem_description": "project settings mutation lacks project admin authorization",
        "evidence": "missing project_admin check before mutating project settings",
    },
    {
        "agent_id": "coding_agent",
        "severity": "medium",
        "confidence": 0.83,
        "dedupe_hash": "hash_coding",
        "file_path": "backend/api/project.py",
        "line_start": 88,
        "title": "weak validation",
        "problem_description": "state mutation branch has weak validation",
        "evidence": "state mutation branch has weak validation",
    },
    {
        "agent_id": "performance_agent",
        "severity": "high",
        "confidence": 0.68,
        "dedupe_hash": "hash_tool_supported",
        "file_path": "backend/cache.py",
        "line_start": 42,
        "title": "redis keys usage",
        "problem_description": "Redis KEYS may block production instance",
        "evidence": "Redis KEYS",
    },
]
tool_observations = [
    {
        "tool_name": "semgrep",
        "rule_id": "REDIS-CMD-003",
        "file_path": "backend/cache.py",
        "line_start": 42,
        "message": "unsafe Redis key scan",
    }
]

conflict_findings = findings + [
    {
        "agent_id": "ddd_agent",
        "disposition": "no_issue",
        "dedupe_hash": "hash_no_issue",
        "file_path": "backend/api/project.py",
        "line_start": 88,
    }
]

conflicts = detect_conflicts(conflict_findings, tool_observations)
assert any(item["type"] == "severity_disagreement" for item in conflicts), conflicts
assert any(item["type"] == "issue_vs_no_issue" for item in conflicts), conflicts
assert any(item["type"] == "tool_supported_low_confidence" for item in conflicts), conflicts
assert any(item["type"] == "high_severity_weak_evidence" for item in conflicts), conflicts

transcripts = run_targeted_debate(conflicts, findings)
assert transcripts, "targeted debate should only run for detected conflicts"
assert all(item["role"] == "debate" for item in transcripts), transcripts
assert all(item["to_agent"] == "judge_findings" for item in transcripts), transcripts

accepted, verifier_rejected = verify_candidate_findings(
    findings + [{"agent_id": "security_agent", "severity": "high", "confidence": 0.4, "dedupe_hash": "low", "file_path": "backend/api/project.py", "line_start": 99, "title": "low confidence", "problem_description": "x"}],
    {"backend/api/project.py", "backend/cache.py"},
    {"security_agent": {"min_confidence": 0.75}, "coding_agent": {"min_confidence": 0.75}, "performance_agent": {"min_confidence": 0.6}},
    set(),
)
assert len(accepted) == 3, accepted
assert verifier_rejected[0]["rejected_reasons"] == ["below_confidence"], verifier_rejected

g1_findings = [
    {
        "agent_id": "security_agent",
        "severity": "high",
        "confidence": 0.91,
        "dedupe_hash": "line",
        "file_path": "backend/api/project.py",
        "line_start": 120,
        "title": "line drift",
        "problem_description": "line not in diff",
        "evidence": "project_admin check before mutating project settings",
        "covered_rules": ["SEC-INJECT-003"],
    },
    {
        "agent_id": "security_agent",
        "severity": "high",
        "confidence": 0.91,
        "dedupe_hash": "evidence",
        "file_path": "backend/api/project.py",
        "line_start": 88,
        "title": "fabricated evidence",
        "problem_description": "evidence not present",
        "evidence": "totally unrelated payment gateway timeout retry",
        "covered_rules": ["SEC-INJECT-003"],
    },
    {
        "agent_id": "security_agent",
        "severity": "high",
        "confidence": 0.91,
        "dedupe_hash": "rule",
        "file_path": "backend/api/project.py",
        "line_start": 88,
        "title": "unknown rule",
        "problem_description": "unknown rule should be rejected",
        "evidence": "project_admin check before mutating project settings",
        "covered_rules": ["MADE-UP-RULE"],
    },
]
g1_accepted, g1_rejected = verify_candidate_findings(
    g1_findings,
    {"backend/api/project.py"},
    {"security_agent": {"min_confidence": 0.75}},
    set(),
    {"backend/api/project.py": [(85, 90)]},
    {"SEC-INJECT-003"},
    lambda _file, _line, window=5: "project_admin check before mutating project settings",
)
assert len(g1_accepted) == 1, g1_accepted
assert g1_accepted[0]["dedupe_hash"] == "rule", g1_accepted
assert "unknown_rule" in g1_accepted[0].get("verification_flags", []), g1_accepted
assert [item["rejected_reasons"][0] for item in g1_rejected] == ["line_out_of_diff", "evidence_not_in_source"], g1_rejected

tool_supported_accepted, tool_supported_rejected = verify_candidate_findings(
    [
        {
            "agent_id": "security_agent",
            "severity": "high",
            "confidence": 0.91,
            "dedupe_hash": "tool-supported",
            "file_path": "backend/api/project.py",
            "line_start": 88,
            "title": "SQL 拼接存在注入风险",
            "problem_description": "tool backed finding should not be rejected only because prose evidence differs from source snippet",
            "evidence": "新增代码将外部输入拼接进 SQL 后执行",
            "covered_rules": ["SEC-INJECT-003"],
        }
    ],
    {"backend/api/project.py"},
    {"security_agent": {"min_confidence": 0.75}},
    set(),
    {"backend/api/project.py": [(85, 90)]},
    {"SEC-INJECT-003"},
    lambda _file, _line, window=5: "Statement statement = connection.createStatement(); ResultSet rs = statement.executeQuery(sql);",
    [{"tool_name": "semgrep", "rule_id": "SEC-INJECT-003", "file_path": "backend/api/project.py", "line_start": 88, "message": "JDBC SQL concat"}],
)
assert len(tool_supported_accepted) == 1, (tool_supported_accepted, tool_supported_rejected)

final_findings, judge_rejected = judge_candidate_findings(accepted, conflicts, max_findings=3)
assert len(final_findings) == 3, final_findings
assert any(item.get("judge_adjustment") == "downgraded_high_severity_weak_evidence" for item in final_findings), final_findings
assert all(item["selected"] in {0, 1} for item in final_findings), final_findings
debate_adjusted, debate_rejected = apply_debate_verdicts(
    [
        {"dedupe_hash": "drop_me", "severity": "high", "confidence": 0.93},
        {"dedupe_hash": "downgrade_me", "severity": "critical", "confidence": 0.94},
        {"dedupe_hash": "keep_me", "severity": "medium", "confidence": 0.5},
    ],
    [
        {"finding_hashes": ["drop_me"], "verdict": "drop", "reason": "not in diff"},
        {"finding_hashes": ["downgrade_me"], "verdict": "downgrade", "calibrated_severity": "medium", "calibrated_confidence": 0.71},
        {"finding_hashes": ["keep_me"], "verdict": "keep", "calibrated_confidence": 0.82},
    ],
)
assert len(debate_rejected) == 1 and debate_rejected[0]["rejected_reasons"] == ["debate_drop"], debate_rejected
debate_by_hash = {item["dedupe_hash"]: item for item in debate_adjusted}
assert debate_by_hash["downgrade_me"]["severity"] == "medium", debate_by_hash
assert debate_by_hash["downgrade_me"]["judge_adjustment"] == "debate_downgraded", debate_by_hash
assert debate_by_hash["keep_me"]["confidence"] == 0.82, debate_by_hash
tool_supported_finding = next(item for item in final_findings if item["file_path"] == "backend/cache.py")
matched_observations = match_tool_observations_for_finding(tool_supported_finding, tool_observations)
assert matched_observations, (tool_supported_finding, tool_observations)
assert matched_observations[0]["tool_name"] == "semgrep", matched_observations
dep_scope_matches = match_tool_observations_for_finding(
    {
        "agent_id": "dependency_agent",
        "severity": "medium",
        "confidence": 0.9,
        "dedupe_hash": "dep-scope",
        "file_path": "pom.xml",
        "line_start": 13,
        "title": "junit-jupiter 依赖未声明 test scope",
        "covered_rules": ["DEP-SCOPE-005"],
    },
    [
        {"tool_name": "java_web_static", "rule_id": "DEP-SCOPE-005", "file_path": "pom.xml", "line_start": 13, "message": "测试依赖未限定 scope"},
        {"tool_name": "trivy", "rule_id": "CVE-2025-70974", "file_path": "pom.xml", "line_start": None, "message": "fastjson RCE"},
    ],
)
assert [item["rule_id"] for item in dep_scope_matches] == ["DEP-SCOPE-005"], dep_scope_matches
open_source_promoted = promote_tool_observations(
    [
        {
            "tool_name": "checkstyle",
            "rule_id": "ALI-NAMING-001",
            "severity": "medium",
            "confidence": 0.84,
            "file_path": "src/main/java/com/acme/payment/PaymentService.java",
            "line_start": 12,
            "message": "类名或成员命名不符合 Java 规范",
        },
        {
            "tool_name": "spotbugs",
            "rule_id": "HW-SEC-001",
            "severity": "high",
            "confidence": 0.86,
            "file_path": "src/main/java/com/acme/payment/TokenService.java",
            "line_start": 44,
            "message": "java.util.Random is used for security-sensitive token generation",
        },
        {
            "tool_name": "dependency-check",
            "rule_id": "DEP-CVE-001",
            "severity": "critical",
            "confidence": 0.9,
            "file_path": "pom.xml",
            "line_start": 18,
            "message": "dependency has known critical CVE",
        },
    ],
    [],
)
assert len(open_source_promoted) == 3, open_source_promoted
assert {item["agent_id"] for item in open_source_promoted} == {"coding_agent", "security_agent", "dependency_agent"}, open_source_promoted
semgrep_domain_promoted = promote_tool_observations(
    [
        {
            "tool_name": "semgrep",
            "rule_id": "jolt.java.client-controlled-risk-bypass",
            "severity": "high",
            "confidence": 0.96,
            "file_path": "src/main/java/com/acme/payment/PaymentService.java",
            "line_start": 90,
            "message": "Client-controlled request data or loopback IP is used to bypass risk control.",
        },
        {
            "tool_name": "semgrep",
            "rule_id": "jolt.java.weak-webhook-signature-match",
            "severity": "high",
            "confidence": 0.86,
            "file_path": "src/main/java/com/acme/payment/WebhookService.java",
            "line_start": 30,
            "message": "Webhook signature trust uses string prefix/substring matching.",
        },
        {
            "tool_name": "semgrep",
            "rule_id": "jolt.config.jpa-show-sql-enabled",
            "severity": "high",
            "confidence": 0.86,
            "file_path": "src/main/resources/application.yml",
            "line_start": 13,
            "message": "spring.jpa.show-sql is enabled.",
        },
        {
            "tool_name": "semgrep",
            "rule_id": "jolt.test.skip-high-risk-path-tests",
            "severity": "high",
            "confidence": 0.86,
            "file_path": "src/test/resources/application-test.yml",
            "line_start": 24,
            "message": "Test configuration skips high-risk path tests.",
        },
    ],
    [],
)
assert {item["tool_rule_id"] for item in semgrep_domain_promoted} == {
    "SEC-RISK-006",
    "SEC-WEBHOOK-008",
    "SEC-CONFIG-007",
    "TEST-COVER-001",
}, semgrep_domain_promoted
semgrep_rare_java_promoted = promote_tool_observations(
    [
        {
            "tool_name": "semgrep",
            "rule_id": "jolt.java.threadlocal-set-without-remove",
            "severity": "high",
            "confidence": 0.92,
            "file_path": "src/main/java/com/acme/payment/RareIssueAuditService.java",
            "line_start": 49,
            "message": "ThreadLocal is written in a request/service path without remove().",
        },
        {
            "tool_name": "semgrep",
            "rule_id": "jolt.java.bigdecimal-double-constructor",
            "severity": "high",
            "confidence": 0.92,
            "file_path": "src/main/java/com/acme/payment/RareIssueAuditService.java",
            "line_start": 65,
            "message": "BigDecimal is constructed from double arithmetic.",
        },
        {
            "tool_name": "semgrep",
            "rule_id": "jolt.java.signature-string-equals",
            "severity": "high",
            "confidence": 0.92,
            "file_path": "src/main/java/com/acme/payment/RareIssueAuditService.java",
            "line_start": 57,
            "message": "Security signature is compared with String.equals.",
        },
        {
            "tool_name": "semgrep",
            "rule_id": "jolt.java.spring-debug-endpoint-method",
            "severity": "high",
            "confidence": 0.92,
            "file_path": "src/main/java/com/acme/payment/RareIssueAuditController.java",
            "line_start": 39,
            "message": "Spring MVC debug endpoint exposes runtime state.",
        },
        {
            "tool_name": "semgrep",
            "rule_id": "jolt.java.transactional-self-invocation",
            "severity": "high",
            "confidence": 0.92,
            "file_path": "src/main/java/com/acme/payment/RareIssueAuditService.java",
            "line_start": 96,
            "message": "A @Transactional method is invoked through self inside the same class.",
        },
    ],
    [],
)
assert {item["tool_rule_id"] for item in semgrep_rare_java_promoted} == {
    "ALI-CONCURRENCY-003",
    "ALI-BIGDECIMAL-001",
    "SEC-CRYPTO-010",
    "SEC-DEBUG-011",
    "HW-TX-001",
}, semgrep_rare_java_promoted

with tempfile.TemporaryDirectory() as tmp_semgrep:
    worktree = Path(tmp_semgrep) / "worktree"
    source_file = worktree / "src/main/java/com/acme/payment/PaymentService.java"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text(
        "\n".join(
            [
                "package com.acme.payment;",
                "class PaymentService {",
                "  void confirm(Request request) {",
                '    boolean skipRisk = "127.0.0.1".equals(request.clientIp()) || request.skipRiskCheck();',
                "  }",
                "}",
            ]
        )
        + "\n",
        "utf-8",
    )
    semgrep_report = Path(tmp_semgrep) / "semgrep.json"
    semgrep_report.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "check_id": "jolt.java.client-controlled-risk-bypass",
                        "path": str(source_file),
                        "start": {"line": 4},
                        "extra": {
                            "severity": "ERROR",
                            "message": "Client-controlled request data or loopback IP is used to bypass risk control.",
                            "lines": "requires login",
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        "utf-8",
    )
    semgrep_findings = parse_semgrep_findings(
        semgrep_report,
        worktree,
        {"src/main/java/com/acme/payment/PaymentService.java": ChangedFile("src/main/java/com/acme/payment/PaymentService.java", "modified", 1, 0, 1, "@@ -4 +4 @@\n+skipRisk")},
        "sha",
    )
    assert "127.0.0.1" in semgrep_findings[0]["evidence"], semgrep_findings
    assert "clientIp" in semgrep_findings[0]["evidence"], semgrep_findings

static_observations_include_evidence = findings_to_observations(
    [
        {
            "tool_name": "semgrep",
            "tool_rule_id": "jolt.java.client-controlled-risk-bypass",
            "severity": "high",
            "confidence": 0.96,
            "file_path": "src/main/java/com/acme/payment/PaymentService.java",
            "line_start": 90,
            "problem_description": "Client-controlled request data or loopback IP is used to bypass risk control.",
            "evidence": 'if ("127.0.0.1".equals(request.clientIp()) || request.skipRiskCheck()) {',
        }
    ]
)
assert "127.0.0.1" in static_observations_include_evidence[0].message, static_observations_include_evidence
assert "clientIp" in static_observations_include_evidence[0].message, static_observations_include_evidence
aggregated_tool_promoted = promote_tool_observations(
    [
        {
            "tool_name": "semgrep",
            "rule_id": "jolt.java.sensitive-payment-field",
            "severity": "high",
            "confidence": 0.96,
            "file_path": "src/main/java/com/acme/payment/PaymentOrder.java",
            "line_start": 24,
            "message": "Payment credential field cardNumber is stored on the entity.",
        },
        {
            "tool_name": "semgrep",
            "rule_id": "jolt.java.sensitive-payment-field",
            "severity": "high",
            "confidence": 0.96,
            "file_path": "src/main/java/com/acme/payment/PaymentOrder.java",
            "line_start": 40,
            "message": "Payment credential field cvv is stored on the entity.",
        },
        {
            "tool_name": "semgrep",
            "rule_id": "jolt.java.sensitive-data-logging",
            "severity": "high",
            "confidence": 0.96,
            "file_path": "src/main/java/com/acme/payment/PaymentService.java",
            "line_start": 74,
            "message": "Logger call includes sensitive cardNumber/cvv/callbackUrl fields.",
        },
    ],
    [],
)
assert len(aggregated_tool_promoted) == 3, aggregated_tool_promoted
payment_order_lines = {
    item["line_start"]
    for item in aggregated_tool_promoted
    if item["file_path"].endswith("PaymentOrder.java")
}
assert payment_order_lines == {24, 40}, aggregated_tool_promoted
static_priority_findings, static_priority_rejected = judge_candidate_findings(
    [
        *[
            {
                "agent_id": f"agent_{i}",
                "severity": "high",
                "confidence": 0.86,
                "dedupe_hash": f"llm_{i}",
                "file_path": f"src/main/java/com/acme/F{i}.java",
                "line_start": 10,
                "title": f"category filler {i}",
                "covered_rules": [f"CUSTOM-{i:03d}"],
            }
            for i in range(4)
        ],
        {
            "agent_id": "security_agent",
            "severity": "high",
            "confidence": 0.96,
            "dedupe_hash": "tool_sensitive_logging",
            "file_path": "src/main/java/com/acme/payment/PaymentService.java",
            "line_start": 74,
            "title": "sensitive data logged",
            "covered_rules": ["SEC-SECRET-004"],
            "tool_name": "semgrep",
            "tool_rule_id": "SEC-SECRET-004",
            "source_tool_observation": {
                "tool_name": "semgrep",
                "rule_id": "jolt.java.sensitive-data-logging",
                "file_path": "src/main/java/com/acme/payment/PaymentService.java",
                "line_start": 74,
                "message": "Logger call includes sensitive cardNumber/cvv/callbackUrl fields.",
            },
            "verification_flags": ["tool_promoted"],
        },
        {
            "agent_id": "security_agent",
            "severity": "high",
            "confidence": 0.96,
            "dedupe_hash": "tool_risk_bypass",
            "file_path": "src/main/java/com/acme/payment/PaymentService.java",
            "line_start": 90,
            "title": "client controlled risk bypass",
            "covered_rules": ["SEC-RISK-006"],
            "tool_name": "semgrep",
            "tool_rule_id": "SEC-RISK-006",
            "source_tool_observation": {
                "tool_name": "semgrep",
                "rule_id": "jolt.java.client-controlled-risk-bypass",
                "file_path": "src/main/java/com/acme/payment/PaymentService.java",
                "line_start": 90,
                "message": "Client-controlled request data or loopback IP is used to bypass risk control.",
            },
            "verification_flags": ["tool_promoted"],
        },
    ],
    [],
    max_findings=4,
)
assert {"sensitive data logged", "client controlled risk bypass"}.issubset(
    {item["title"] for item in static_priority_findings}
), (static_priority_findings, static_priority_rejected)
tool_flood_findings, tool_flood_rejected = judge_candidate_findings(
    [
        *[
            {
                "agent_id": "security_agent",
                "severity": "high",
                "confidence": 0.96,
                "dedupe_hash": f"tool_secret_{i}",
                "file_path": f"src/main/java/com/acme/payment/Secret{i}.java",
                "line_start": 10,
                "title": f"promoted sensitive field {i}",
                "covered_rules": ["SEC-SECRET-004"],
                "tool_name": "semgrep",
                "tool_rule_id": "SEC-SECRET-004",
                "source_tool_observation": {
                    "tool_name": "semgrep",
                    "rule_id": "jolt.java.sensitive-payment-field",
                    "file_path": f"src/main/java/com/acme/payment/Secret{i}.java",
                    "line_start": 10,
                    "message": "Payment credential-like field is present in Java source.",
                },
                "verification_flags": ["tool_promoted"],
            }
            for i in range(6)
        ],
        {
            "agent_id": "coding_agent",
            "severity": "high",
            "confidence": 0.9,
            "dedupe_hash": "money_precision",
            "file_path": "src/main/java/com/acme/payment/MoneyNormalizer.java",
            "line_start": 8,
            "title": "BigDecimal doubleValue precision loss",
            "covered_rules": ["ALI-BIGDECIMAL-001"],
        },
        {
            "agent_id": "coding_agent",
            "severity": "high",
            "confidence": 0.9,
            "dedupe_hash": "refund_state",
            "file_path": "src/main/java/com/acme/payment/RefundService.java",
            "line_start": 43,
            "title": "Refund allows already-refunded payments",
            "covered_rules": ["CODE-STATE-004"],
        },
    ],
    [],
    max_findings=4,
)
assert {"BigDecimal doubleValue precision loss", "Refund allows already-refunded payments"}.issubset(
    {item["title"] for item in tool_flood_findings}
), (tool_flood_findings, tool_flood_rejected)
category_findings, category_rejected = judge_candidate_findings(
    [
        {
            "agent_id": "security_agent",
            "severity": "high",
            "confidence": 0.99,
            "dedupe_hash": "secret-1",
            "file_path": "PaymentOrder.java",
            "line_start": 24,
            "title": "PaymentOrder stores cardNumber and cvv fields",
            "covered_rules": ["SEC-SECRET-004"],
        },
        {
            "agent_id": "security_agent",
            "severity": "high",
            "confidence": 0.98,
            "dedupe_hash": "secret-2",
            "file_path": "PaymentResponse.java",
            "line_start": 16,
            "title": "card data response leak",
            "covered_rules": ["SEC-SECRET-004"],
        },
        {
            "agent_id": "coding_agent",
            "severity": "high",
            "confidence": 0.9,
            "dedupe_hash": "money",
            "file_path": "MoneyNormalizer.java",
            "line_start": 10,
            "title": "BigDecimal doubleValue precision loss",
            "covered_rules": ["ALI-BIGDECIMAL-001"],
        },
    ],
    [],
    max_findings=2,
)
assert {item["file_path"] for item in category_findings} == {"PaymentOrder.java", "PaymentResponse.java"}, (category_findings, category_rejected)
assert {item["normalized_rule_category"] for item in category_findings} == {"SECRET_LEAK"}, category_findings
assert {item.get("semantic_category") for item in category_findings} == {"SENSITIVE_DATA_STORAGE", "SENSITIVE_DATA_RESPONSE"}, category_findings

domain_priority_findings, domain_priority_rejected = judge_candidate_findings(
    [
        {
            "agent_id": "database_agent",
            "severity": "high",
            "confidence": 0.89,
            "dedupe_hash": "like_wildcard",
            "file_path": "src/main/java/com/acme/payment/application/PaymentDddApplicationService.java",
            "line_start": 66,
            "title": "LIKE 前导通配符导致索引失效",
            "problem_description": "search 使用 LIKE '%keyword%' 左模糊查询，无法使用普通索引。",
            "covered_rules": ["PERF-QUERY-001"],
        },
        {
            "agent_id": "test_agent",
            "severity": "high",
            "confidence": 0.9,
            "dedupe_hash": "app_service_test",
            "file_path": "src/main/java/com/acme/payment/application/PaymentDddApplicationService.java",
            "line_start": 14,
            "title": "PaymentDddApplicationService forceTransition 缺少状态迁移测试",
            "problem_description": "应用服务新增 forceTransition 状态流转入口但缺少异常路径和分支测试。",
            "covered_rules": ["TEST-COVER-001"],
        },
        {
            "agent_id": "test_agent",
            "severity": "high",
            "confidence": 0.93,
            "dedupe_hash": "controller_test_gap",
            "file_path": "src/main/java/com/acme/payment/api/PaymentController.java",
            "line_start": 18,
            "title": "Controller 缺少 MockMvc 测试",
            "covered_rules": ["TEST-COVER-001"],
        },
    ],
    [],
    max_findings=2,
)
assert {item.get("semantic_category") for item in domain_priority_findings} == {
    "LIKE_LEADING_WILDCARD_INDEX_RISK",
    "MISSING_APP_SERVICE_TEST_COVERAGE",
}, domain_priority_findings
substantive_priority_findings, substantive_priority_rejected = judge_candidate_findings(
    [
        {
            "agent_id": "test_agent",
            "severity": "high",
            "confidence": 0.93,
            "dedupe_hash": "test_gap",
            "file_path": "src/main/java/com/acme/payment/PaymentService.java",
            "line_start": 29,
            "title": "PaymentService 构造与创建流程变更缺少回归测试",
            "covered_rules": ["TEST-COVER-001", "TEST-ASSERT-002"],
        },
        {
            "agent_id": "ddd_agent",
            "severity": "medium",
            "confidence": 0.86,
            "dedupe_hash": "ddd_event",
            "file_path": "src/main/java/com/acme/payment/NotificationService.java",
            "line_start": 14,
            "title": "NotificationService 缺失领域事件抽象",
            "covered_rules": ["DDD-EVENT-006"],
        },
        {
            "agent_id": "coding_agent",
            "severity": "high",
            "confidence": 0.88,
            "dedupe_hash": "money_precision_priority",
            "file_path": "src/main/java/com/acme/payment/MoneyNormalizer.java",
            "line_start": 9,
            "title": "MoneyNormalizer 使用 doubleValue 转换导致金额精度丢失",
            "covered_rules": ["ALI-BIGDECIMAL-001"],
        },
        {
            "agent_id": "coding_agent",
            "severity": "high",
            "confidence": 0.86,
            "dedupe_hash": "refund_state_priority",
            "file_path": "src/main/java/com/acme/payment/RefundService.java",
            "line_start": 43,
            "title": "退款状态判定允许 REFUNDED 状态，破坏退款状态机一致性",
            "covered_rules": ["CODE-STATE-004"],
        },
    ],
    [],
    max_findings=2,
)
assert {item["file_path"] for item in substantive_priority_findings} == {
    "src/main/java/com/acme/payment/MoneyNormalizer.java",
    "src/main/java/com/acme/payment/RefundService.java",
}, (substantive_priority_findings, substantive_priority_rejected)
state_location_findings, state_location_rejected = judge_candidate_findings(
    [
        {
            "agent_id": "coding_agent",
            "severity": "high",
            "confidence": 0.86,
            "dedupe_hash": "refund_domain_tool",
            "file_path": "src/main/java/com/acme/payment/domain/PaymentOrder.java",
            "line_start": 137,
            "title": "Refund logic allows already-refunded payments; enforce refund state machine",
            "covered_rules": ["CODE-STATE-004"],
            "tool_name": "semgrep",
            "tool_rule_id": "CODE-STATE-004",
            "source_tool_observation": {
                "tool_name": "semgrep",
                "rule_id": "jolt.java.refund-allows-refunded-state",
                "file_path": "src/main/java/com/acme/payment/domain/PaymentOrder.java",
                "line_start": 137,
                "message": "Refund logic allows already-refunded payments.",
            },
            "verification_flags": ["tool_promoted"],
        },
        {
            "agent_id": "coding_agent",
            "severity": "high",
            "confidence": 0.86,
            "dedupe_hash": "refund_service_tool",
            "file_path": "src/main/java/com/acme/payment/service/RefundService.java",
            "line_start": 43,
            "title": "Refund logic allows already-refunded payments; enforce refund state machine and cumulative amount checks",
            "covered_rules": ["CODE-STATE-004"],
            "tool_name": "semgrep",
            "tool_rule_id": "CODE-STATE-004",
            "source_tool_observation": {
                "tool_name": "semgrep",
                "rule_id": "jolt.java.refund-allows-refunded-state",
                "file_path": "src/main/java/com/acme/payment/service/RefundService.java",
                "line_start": 43,
                "message": "Refund logic allows already-refunded payments.",
            },
            "verification_flags": ["tool_promoted"],
        },
    ],
    [],
    max_findings=1,
)
assert state_location_findings[0]["file_path"].endswith("RefundService.java"), (state_location_findings, state_location_rejected)

diff_anchor_files = [
    ChangedFile(
        "src/main/java/com/acme/payment/domain/PaymentOrder.java",
        "modified",
        4,
        0,
        4,
        "@@ -112,4 +112,14 @@ public void markRefunded() {\n"
        "         this.status = PaymentStatus.REFUNDED;\n"
        "         this.updatedAt = Instant.now();\n"
        "     }\n"
        "+\n"
        "+    public void overrideStatus(String status) {\n"
        "+        this.status = PaymentStatus.valueOf(status);\n"
        "+        this.updatedAt = Instant.now();\n"
        "+    }\n",
    ),
    ChangedFile(
        "src/main/java/com/acme/payment/service/NotificationService.java",
        "modified",
        2,
        0,
        2,
        "@@ -20,3 +20,5 @@ public void notifyMerchant() {\n"
        "     auditStart();\n"
        "+    URI callbackUrl = validateCallbackUrl(order.getCallbackUrl());\n"
        "+    restTemplate.postForEntity(callbackUrl, payload, String.class);\n"
        " }\n",
    ),
]
kept_tool_observations, rejected_tool_observations = filter_tool_observations_to_added_lines(
    [
        {
            "tool_name": "semgrep",
            "rule_id": "jolt.java.refund-allows-refunded-state",
            "file_path": "src/main/java/com/acme/payment/domain/PaymentOrder.java",
            "line_start": 112,
            "message": "Refund logic allows already-refunded payments.",
        },
        {
            "tool_name": "semgrep",
            "rule_id": "CODE-STATE-004",
            "file_path": "src/main/java/com/acme/payment/domain/PaymentOrder.java",
            "line_start": 116,
            "message": "overrideStatus directly trusts external status.",
        },
    ],
    diff_anchor_files,
)
assert len(kept_tool_observations) == 1 and kept_tool_observations[0]["line_start"] == 116, (
    kept_tool_observations,
    rejected_tool_observations,
)
assert rejected_tool_observations[0]["rejected_reasons"] == ["tool_observation_not_on_added_line"], rejected_tool_observations

diff_kept_findings, diff_rejected_findings = filter_to_diff_introduced_findings(
    [
        {
            "agent_id": "coding_agent",
            "severity": "high",
            "confidence": 0.86,
            "dedupe_hash": "old_context_refund",
            "file_path": "src/main/java/com/acme/payment/domain/PaymentOrder.java",
            "line_start": 112,
            "title": "markRefunded allows already-refunded payments",
            "covered_rules": ["CODE-STATE-004"],
        },
        {
            "agent_id": "coding_agent",
            "severity": "high",
            "confidence": 0.88,
            "dedupe_hash": "callback_url",
            "file_path": "src/main/java/com/acme/payment/service/NotificationService.java",
            "line_start": 23,
            "title": "restTemplate.postForEntity callbackUrl external call requires validation and timeout",
            "covered_rules": ["SEC-SSRF-009"],
        },
    ],
    diff_anchor_files,
)
assert len(diff_kept_findings) == 1 and diff_kept_findings[0]["line_start"] == 22, (
    diff_kept_findings,
    diff_rejected_findings,
)
assert diff_kept_findings[0]["quality_trace"]["original_line_start"] == 23, diff_kept_findings
assert diff_rejected_findings[0]["rejected_reasons"] == ["context_line_not_semantically_tied_to_added_line"], diff_rejected_findings

redis_guard_conn = sqlite3.connect(":memory:")
redis_guard_conn.row_factory = sqlite3.Row
redis_guard_conn.executescript(
    """
    CREATE TABLE review_findings (
      id TEXT, review_run_id TEXT, severity TEXT, confidence REAL, agent_id TEXT,
      head_sha TEXT, dedupe_hash TEXT, file_path TEXT, line_start INTEGER, line_end INTEGER,
      title TEXT, problem_description TEXT, recommendation TEXT, suggested_code TEXT, evidence TEXT,
      covered_rules_json TEXT, skipped_rules_json TEXT, tool_provenance_json TEXT,
      source_observations_json TEXT, quality_trace_json TEXT, selected INTEGER DEFAULT 1
    );
    CREATE TABLE tool_observations (
      id TEXT, review_run_id TEXT, tool_name TEXT, rule_id TEXT, severity TEXT, confidence REAL,
      file_path TEXT, line_start INTEGER, line_end INTEGER, message TEXT, raw_artifact_id TEXT,
      adopted_by_agent TEXT, adoption_state TEXT
    );
    CREATE TABLE rule_precision_history (
      project_id TEXT, agent_id TEXT, rule_id TEXT, accepted_count INTEGER,
      rejected_count INTEGER, auto_suppress INTEGER
    );
    """
)

class GuardRecorder:
    def span(self, *_args, **_kwargs):
        return "span"
    def event(self, *_args, **_kwargs):
        pass
    def finish(self, *_args, **_kwargs):
        pass

redis_guard_node = make_judge_findings_node(
    conn=redis_guard_conn,
    recorder=GuardRecorder(),
    job={"head_sha": "sha"},
    project_id="project_default",
    run_id="run_redis_guard",
    new_id=lambda prefix: f"{prefix}_1",
    load_tool_observations=lambda _conn, _run_id: [
        {
            "tool_name": "semgrep",
            "rule_id": "jolt.hardcoded-password",
            "severity": "high",
            "confidence": 0.88,
            "file_path": "src/main/java/com/acme/payment/service/PaymentService.java",
            "line_start": 95,
            "message": "Hardcoded token-like value.",
        }
    ],
    max_findings=5,
)
redis_guard_state = redis_guard_node(
    {
        "files": [
            ChangedFile(
                "src/main/java/com/acme/payment/service/PaymentService.java",
                "modified",
                1,
                0,
                1,
                "@@ -94,2 +94,3 @@\n"
                "+audits.write(\"confirmed token=\" + request.settlementToken());\n",
            )
        ],
        "verified_findings": [
            {
                "agent_id": "redis_agent",
                "severity": "medium",
                "confidence": 0.82,
                "dedupe_hash": "redis_false_positive",
                "file_path": "src/main/java/com/acme/payment/service/PaymentService.java",
                "line_start": 95,
                "title": "Redis 缓存写入缺少 TTL",
                "problem_description": "当前代码使用 ConcurrentHashMap 或日志 token，未发现 RedisTemplate 调用。",
                "covered_rules": ["REDIS-TTL-002"],
                "suggested_code": "redisTemplate.opsForValue().set(key, value, Duration.ofMinutes(30));",
            }
        ],
        "conflicts": [],
        "debate_results": [],
        "tool_observations": [
            {
                "tool_name": "semgrep",
                "rule_id": "jolt.hardcoded-password",
                "severity": "high",
                "confidence": 0.88,
                "file_path": "src/main/java/com/acme/payment/service/PaymentService.java",
                "line_start": 95,
                "message": "Hardcoded token-like value.",
            }
        ],
    }
)
assert not redis_guard_state["final_findings"], redis_guard_state["final_findings"]

error_leak_coverage_findings, error_leak_coverage_rejected = judge_candidate_findings(
    [
        {
            "agent_id": "security_agent",
            "severity": "high",
            "confidence": 0.95,
            "dedupe_hash": "card_response",
            "file_path": "src/main/java/com/acme/payment/api/dto/PaymentResponse.java",
            "line_start": 16,
            "title": "PaymentResponse returns cardNumber and cvv",
            "covered_rules": ["SEC-SECRET-004"],
            "tool_name": "semgrep",
            "tool_rule_id": "SEC-SECRET-004",
            "verification_flags": ["tool_promoted"],
        },
        {
            "agent_id": "security_agent",
            "severity": "high",
            "confidence": 0.92,
            "dedupe_hash": "stacktrace_response",
            "file_path": "src/main/java/com/acme/payment/api/GlobalExceptionHandler.java",
            "line_start": 27,
            "title": "Stack traces are returned to API clients",
            "covered_rules": ["SEC-SECRET-004:ERROR_RESPONSE"],
            "tool_name": "semgrep",
            "tool_rule_id": "SEC-SECRET-004:ERROR_RESPONSE",
            "verification_flags": ["tool_promoted"],
        },
        {
            "agent_id": "coding_agent",
            "severity": "high",
            "confidence": 0.9,
            "dedupe_hash": "money_after_error",
            "file_path": "src/main/java/com/acme/payment/MoneyNormalizer.java",
            "line_start": 9,
            "title": "BigDecimal doubleValue precision loss",
            "covered_rules": ["ALI-BIGDECIMAL-001"],
        },
    ],
    [],
    max_findings=2,
)
assert {item["file_path"] for item in error_leak_coverage_findings} == {
    "src/main/java/com/acme/payment/api/dto/PaymentResponse.java",
    "src/main/java/com/acme/payment/api/GlobalExceptionHandler.java",
}, (error_leak_coverage_findings, error_leak_coverage_rejected)
auxiliary_overlap_findings, auxiliary_overlap_rejected = judge_candidate_findings(
    [
        {
            "agent_id": "security_agent",
            "severity": "high",
            "confidence": 0.95,
            "dedupe_hash": "admin_auth",
            "file_path": "src/main/java/com/acme/payment/api/AccountController.java",
            "line_start": 36,
            "title": "admin adjustment endpoint lacks authentication and authorization",
            "covered_rules": ["SEC-AUTHZ-002"],
            "tool_name": "semgrep",
            "tool_rule_id": "SEC-AUTHZ-002",
            "verification_flags": ["tool_promoted"],
        },
        {
            "agent_id": "backend_agent",
            "severity": "high",
            "confidence": 0.86,
            "dedupe_hash": "admin_idempotency_aux",
            "file_path": "src/main/java/com/acme/payment/api/AccountController.java",
            "line_start": 36,
            "title": "管理员余额调整接口缺少幂等控制",
            "covered_rules": ["BE-IDEMP-004"],
        },
        {
            "agent_id": "test_agent",
            "severity": "high",
            "confidence": 0.9,
            "dedupe_hash": "admin_test_aux",
            "file_path": "src/main/java/com/acme/payment/api/AccountController.java",
            "line_start": 36,
            "title": "新增 admin adjustment 端点缺少 Controller 测试覆盖",
            "covered_rules": ["TEST-COVER-001"],
        },
        {
            "agent_id": "coding_agent",
            "severity": "high",
            "confidence": 0.88,
            "dedupe_hash": "refund_amount_core",
            "file_path": "src/main/java/com/acme/payment/service/RefundService.java",
            "line_start": 43,
            "title": "Refund allows already-refunded payments and cumulative amount can exceed paid amount",
            "covered_rules": ["CODE-STATE-004"],
        },
    ],
    [],
    max_findings=3,
)
assert {item["title"] for item in auxiliary_overlap_findings} == {
    "admin adjustment endpoint lacks authentication and authorization",
    "Refund allows already-refunded payments and cumulative amount can exceed paid amount",
}, (auxiliary_overlap_findings, auxiliary_overlap_rejected)
assert any(
    item.get("title") == "管理员余额调整接口缺少幂等控制" and "auxiliary_overlap_core_issue" in item.get("rejected_reasons", [])
    for item in auxiliary_overlap_rejected
), auxiliary_overlap_rejected
limited_findings, limited_rejected = judge_candidate_findings(accepted, conflicts, max_findings=2)
assert len(limited_findings) == 2, limited_findings
assert any("max_findings_exceeded" in item["rejected_reasons"] for item in limited_rejected), limited_rejected
assert "detect_conflicts" in EXECUTED_GRAPH_NODE_KEYS
assert "run_targeted_debate" in EXECUTED_GRAPH_NODE_KEYS
assert "build_context" in TARGET_GRAPH_NODE_KEYS
assert "run_experts" in TARGET_GRAPH_NODE_KEYS

standard_budget = budget_for_effort("standard")
assert standard_budget["max_cost_usd"] == 1.0, standard_budget
assert standard_budget["max_wall_seconds"] == 900, standard_budget
assert standard_budget["max_llm_calls"] == 24, standard_budget
assert standard_budget["max_llm_calls"] >= 1, standard_budget
cost_tracker = BudgetTracker.from_budget(standard_budget)
for _ in range(100):
    if cost_tracker.should_stop():
        break
    cost_tracker.charge_llm("MiniMax-M2.7", 50000, 50000)
assert cost_tracker.truncated_reason == "cost_usd_exceeded", cost_tracker.snapshot()

wall_tracker = BudgetTracker(max_wall_seconds=1, max_cost_usd=10, max_llm_calls=10, started_at=time.monotonic() - 2)
assert wall_tracker.should_stop()
assert wall_tracker.truncated_reason == "wall_seconds_exceeded", wall_tracker.snapshot()

call_tracker = BudgetTracker(max_wall_seconds=100, max_cost_usd=10, max_llm_calls=1)
call_tracker.charge_llm("MiniMax-M2.7", 1, 1)
assert call_tracker.truncated_reason == "llm_calls_exceeded", call_tracker.snapshot()

deepagents_source = (ROOT / "worker" / "orchestration" / "deepagents_runner.py").read_text("utf-8")
assert "BoundedReviewChatModel" not in deepagents_source
assert "scripted" not in deepagents_source.lower()
assert "OpenAICompatibleToolChatModel" in deepagents_source
assert "DeepAgents completed without real tool calls" in deepagents_source

code_index = build_diff_graph([
    ChangedFile(
        filename="src/main/java/com/acme/payment/PaymentController.java",
        status="modified",
        additions=12,
        deletions=0,
        changes=12,
        patch="""
@@ -0,0 +1,12 @@
+package com.acme.payment;
+import java.sql.Connection;
+public class PaymentController {
+  public PaymentResult findPayment(String id) {
+    validate(id);
+    return queryPayment(id);
+  }
+  private PaymentResult queryPayment(String id) {
+    return null;
+  }
+}
""",
    )
])
assert code_index["status"] == "indexed", code_index
assert any(item["name"] == "PaymentController" for item in code_index["classes"]), code_index
assert any(item["name"] == "findPayment" for item in code_index["functions"]), code_index
assert "queryPayment" in code_index["callees"], code_index
assert "code_index_snapshots" in (ROOT / "worker" / "orchestration" / "nodes" / "prescan.py").read_text("utf-8")

recorder_conn = sqlite3.connect(":memory:")
recorder_conn.execute("PRAGMA foreign_keys = ON")
recorder_conn.executescript(
    """
    CREATE TABLE agent_trace_spans (
      id TEXT PRIMARY KEY,
      review_run_id TEXT NOT NULL,
      parent_span_id TEXT,
      span_key TEXT NOT NULL,
      agent_id TEXT,
      status TEXT NOT NULL,
      started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      ended_at TEXT
    );
    CREATE TABLE agent_trace_events (
      id TEXT PRIMARY KEY,
      span_id TEXT NOT NULL REFERENCES agent_trace_spans(id),
      event_type TEXT NOT NULL,
      summary TEXT NOT NULL,
      payload_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE agent_messages (
      id TEXT PRIMARY KEY,
      span_id TEXT NOT NULL REFERENCES agent_trace_spans(id),
      from_agent TEXT NOT NULL,
      to_agent TEXT NOT NULL,
      role TEXT NOT NULL,
      content_summary TEXT NOT NULL,
      artifact_id TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE llm_call_records (
      id TEXT PRIMARY KEY,
      span_id TEXT NOT NULL REFERENCES agent_trace_spans(id),
      provider TEXT NOT NULL,
      model TEXT NOT NULL,
      request_id TEXT,
      prompt_hash TEXT,
      input_tokens INTEGER NOT NULL DEFAULT 0,
      output_tokens INTEGER NOT NULL DEFAULT 0,
      duration_ms INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE tool_call_records (
      id TEXT PRIMARY KEY,
      span_id TEXT NOT NULL REFERENCES agent_trace_spans(id),
      tool_name TEXT NOT NULL,
      tool_version TEXT,
      args_summary TEXT NOT NULL DEFAULT '',
      input_ref_json TEXT NOT NULL DEFAULT '{}',
      output_summary TEXT NOT NULL DEFAULT '',
      output_ref_json TEXT NOT NULL DEFAULT '{}',
      duration_ms INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE review_artifacts (
      id TEXT PRIMARY KEY,
      review_run_id TEXT NOT NULL,
      artifact_type TEXT NOT NULL,
      name TEXT NOT NULL,
      storage_uri TEXT NOT NULL,
      sha256 TEXT NOT NULL,
      size_bytes INTEGER NOT NULL DEFAULT 0,
      metadata_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE review_jobs (
      id TEXT PRIMARY KEY,
      requested_effort_level TEXT NOT NULL DEFAULT 'standard',
      pr_summary TEXT NOT NULL DEFAULT '{}',
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """
)
batch_recorder = Recorder(recorder_conn, "run_batch", max_batch=3)
batch_span = batch_recorder.span("batch_test", "tester")
batch_recorder.event(batch_span, "event_a", "a")
assert batch_recorder.flush_count >= 2, batch_recorder.flush_count
batch_recorder.event(batch_span, "event_b", "b")
assert batch_recorder.flush_count >= 3, batch_recorder.flush_count
batch_recorder.finish(batch_span)
batch_recorder.flush()
assert batch_recorder.pending_writes == 0, batch_recorder.pending_writes

with tempfile.TemporaryDirectory(prefix="jolt-worker-logs-") as log_dir:
    file_recorder = Recorder(
        recorder_conn,
        "run_file_log",
        config={"logging": {"enabled": True, "dir": log_dir, "worker_file": "worker.jsonl", "review_run_dir": "runs"}},
    )
    file_span = file_recorder.span("file_log_test", "tester")
    file_recorder.event(file_span, "flow_event", "流程事件")
    file_recorder.tool_call(file_span, "semgrep", "completed", 12, "rules=p/java", "1 finding")
    file_recorder.llm_call(
        file_span,
        "dashscope-openai-compatible",
        "MiniMax-M2.7",
        "prompt",
        "completed",
        34,
        10,
        5,
        "req_1",
        [{"role": "user", "content": "prompt"}],
        "[{\"title\":\"demo\"}]",
    )
    file_recorder.finish(file_span)
    worker_log = Path(log_dir) / "worker.jsonl"
    run_log = Path(log_dir) / "runs" / "run_file_log.jsonl"
    assert worker_log.exists(), worker_log
    assert run_log.exists(), run_log
    worker_log_text = worker_log.read_text("utf-8")
    run_log_text = run_log.read_text("utf-8")
    assert '"event": "tool_call"' in worker_log_text, worker_log_text
    assert '"event": "llm_call"' in worker_log_text, worker_log_text
    assert '"prompt": "prompt"' in worker_log_text, worker_log_text
    assert '"request_messages": [{"role": "user", "content": "prompt"}]' in worker_log_text, worker_log_text
    assert '"response_text": "[{\\"title\\":\\"demo\\"}]"' in worker_log_text, worker_log_text
    assert '"event": "trace_event"' in run_log_text, run_log_text

recorder_conn.execute("INSERT INTO review_jobs (id, requested_effort_level) VALUES ('job_summary', 'fast')")
summary_recorder = Recorder(recorder_conn, "run_summary")

def fail_if_called(*_args, **_kwargs):
    raise AssertionError("fast effort must skip PR summary LLM call")

summary_node = make_summarize_pr_node(
    conn=recorder_conn,
    recorder=summary_recorder,
    job={"id": "job_summary", "requested_effort_level": "fast"},
    mr={
        "id": "mr_summary",
        "number": 284,
        "title": "修复项目权限更新接口",
        "source_branch": "feat/project-setting",
        "target_branch": "master",
        "author": "陈旭",
        "risk_score": 86,
    },
    project_config={},
    summarize_pr=fail_if_called,
)
summary_state = summary_node(
    {
        "effort": "fast",
        "files": [ChangedFile("backend/api/project.py", "modified", 12, 1, 13, "@@ -1 +1 @@\n+project_admin")],
        "final_findings": [
            {
                "severity": "high",
                "file_path": "backend/api/project.py",
                "line_start": 88,
                "title": "缺少项目管理员权限校验",
            }
        ],
    }
)
summary_recorder.flush()
persisted_summary = json.loads(recorder_conn.execute("SELECT pr_summary FROM review_jobs WHERE id = 'job_summary'").fetchone()[0])
assert summary_state["pr_summary"]["skipped"] is True, summary_state
assert persisted_summary["source"] == "disabled", persisted_summary
assert persisted_summary["skip_reason"] == "disabled_by_product_design", persisted_summary
assert not persisted_summary["risk_highlights"], persisted_summary

llm_candidates = candidate_providers(
    {
        "providers": [
            {"provider": "deepseek", "base_url": "https://deepseek.invalid", "model": "deepseek-chat", "api_key": "k", "context": 64000, "tier": "fast"},
            {"provider": "qwen", "base_url": "https://qwen.invalid", "model": "qwen-max", "api_key": "k", "context": 128000, "tier": "balanced"},
            {"provider": "claude", "base_url": "https://claude.invalid", "model": "claude-sonnet-4-6", "api_key": "k", "context": 200000, "tier": "premium"},
        ]
    },
    required_context=150000,
)
assert [item["provider"] for item in llm_candidates] == ["claude"], llm_candidates

vcs_provider_source = (ROOT / "src" / "backend" / "vcs" / "VcsProvider.ts").read_text("utf-8")
github_source = (ROOT / "src" / "backend" / "github.ts").read_text("utf-8")
for required_method in ["fetchDiff", "fetchFiles", "fetchFile", "postComment", "postSummary", "updateStatus", "capabilities"]:
    assert required_method in vcs_provider_source, required_method
assert ".split(\"/\")" in github_source, "GitHub contents path must preserve path separators"
assert ".join(\"/\")" in github_source, "GitHub contents path must preserve path separators"
assert "contents/${encodedPath}" in github_source, "GitHub contents URL must use slash-preserving encoded path"

source_mode_files = [
    ChangedFile("src/main/java/demo/A.java", "modified", 1, 0, 1, "@@ -1 +1 @@\n+class A {}"),
    ChangedFile("src/main/resources/application.yml", "modified", 1, 0, 1, "@@ -1 +1 @@\n+spring:\n"),
    ChangedFile("README.md", "modified", 1, 0, 1, "@@ -1 +1 @@\n+readme"),
]
assert source_content_candidate_count(source_mode_files) == 3
assert source_worktree_mode(configured_worktree=None, source_file_contents={}, files=source_mode_files) == "materialized_diff"
assert (
    source_worktree_mode(
        configured_worktree=None,
        source_worktree=ROOT,
        source_file_contents={},
        files=source_mode_files,
    )
    == "git_source_worktree"
)
assert (
    source_worktree_mode(
        configured_worktree=None,
        source_file_contents={"src/main/java/demo/A.java": "class A {}\n"},
        files=source_mode_files,
    )
    == "partial_fetched_source_files"
)
assert (
    source_worktree_mode(
        configured_worktree=None,
        source_file_contents={
            "src/main/java/demo/A.java": "class A {}\n",
            "src/main/resources/application.yml": "spring:\n",
            "README.md": "readme\n",
        },
        files=source_mode_files,
    )
    == "fetched_source_files"
)

source_repo_dir = Path(tempfile.gettempdir()) / "jolt-codereview-source-worktree-fixture"
if source_repo_dir.exists():
    shutil.rmtree(source_repo_dir)
(source_repo_dir / "src" / "main" / "java" / "demo").mkdir(parents=True)
(source_repo_dir / "src" / "main" / "java" / "demo" / "App.java").write_text("package demo;\nclass App {}\n", "utf-8")
subprocess.run(["git", "init"], cwd=source_repo_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
subprocess.run(["git", "checkout", "-B", "main"], cwd=source_repo_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
subprocess.run(["git", "add", "."], cwd=source_repo_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
subprocess.run(
    ["git", "-c", "user.name=Jolt", "-c", "user.email=jolt@example.com", "commit", "-m", "fixture"],
    cwd=source_repo_dir,
    check=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
source_head = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=source_repo_dir,
    check=True,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
).stdout.strip()
fixture_repo = {
    "provider_config_json": json.dumps({"git_url": str(source_repo_dir)}, ensure_ascii=False),
}
fixture_mr = {"latest_head_sha": source_head}
source_worktree_path, source_worktree_errors = prepare_source_worktree({}, fixture_repo, fixture_mr)  # type: ignore[arg-type]
assert source_worktree_errors == [], source_worktree_errors
assert source_worktree_path, "source worktree path should be prepared"
assert (Path(source_worktree_path) / "src" / "main" / "java" / "demo" / "App.java").exists(), source_worktree_path
assert static_tool_enabled({"tool_policy": {"static_runners": {"semgrep": {"enabled": False}}}}, "semgrep") is False
assert static_tool_enabled({"tool_policy": {"static_runners": {"tree-sitter": {"enabled": False}}}}, "tree_sitter_code_graph") is False
assert static_tool_enabled({"tool_policy": {"enabled_tools": ["tree-sitter"]}}, "tree_sitter_code_graph") is True
assert static_tool_enabled({"tool_policy": {"disabled_tools": ["tree-sitter"]}}, "tree_sitter_code_graph") is False

for heartbeat_file in [ROOT / "worker" / "review_queue" / "job_consumer.py", ROOT / "worker" / "queue" / "job_consumer.py"]:
    heartbeat_source = heartbeat_file.read_text("utf-8")
    assert "PRAGMA journal_mode = WAL" in heartbeat_source, heartbeat_file
    assert "sqlite3.OperationalError" in heartbeat_source, heartbeat_file
    assert "locked" in heartbeat_source, heartbeat_file

migration_source = (ROOT / "src" / "backend" / "db" / "migrations.ts").read_text("utf-8")
judge_source = (ROOT / "worker" / "orchestration" / "nodes" / "judge_findings.py").read_text("utf-8")
for trace_column in ["tool_provenance_json", "source_observations_json", "quality_trace_json"]:
    assert trace_column in migration_source, trace_column
    assert trace_column in judge_source, trace_column
assert "not_selected_final_issue" in judge_source, "Judge must not persist unselected candidates as final review findings"

print(json.dumps({
    "conflict_count": len(conflicts),
    "conflict_types": sorted({item["type"] for item in conflicts}),
    "transcript_count": len(transcripts),
    "verifier_rejected": verifier_rejected,
    "judge_final_count": len(final_findings),
    "judge_rejected_count": len(limited_rejected),
    "standard_budget": standard_budget,
    "budget_tracker_after_cost_test": cost_tracker.snapshot(),
    "deepagents_real_tool_guard": True,
    "code_index": {
        "class_count": len(code_index["classes"]),
        "function_count": len(code_index["functions"]),
        "callee_count": len(code_index["callees"]),
    },
    "recorder_flush_count": batch_recorder.flush_count,
    "fast_pr_summary_skipped": persisted_summary["skip_reason"],
    "llm_router_candidates_for_150k": [item["provider"] for item in llm_candidates],
    "vcs_provider_contract": "complete",
    "source_worktree_prepared": str(source_worktree_path),
    "required_node_files": required_node_files,
    "executed_graph_nodes": EXECUTED_GRAPH_NODE_KEYS,
    "target_graph_nodes": TARGET_GRAPH_NODE_KEYS,
}, ensure_ascii=False, indent=2))
