import fs from "node:fs";

function read(path) {
  return fs.readFileSync(path, "utf-8");
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const runtime = read("worker/review_runtime.py");
const deepagents = read("worker/orchestration/deepagents_runner.py");
const prescan = read("worker/orchestration/nodes/prescan.py");
const runExperts = read("worker/orchestration/nodes/run_experts.py");
const seed = read("src/backend/db/seed.ts");
const agentRoutes = read("src/backend/routes/agents.routes.ts");
const frontend = read("src/frontend/main.tsx");
const styles = read("src/frontend/styles.css");
const projectRoutes = read("src/backend/routes/projects.routes.ts");
const treeSitterTool = read("worker/tools/tree_sitter_tool.py");
const requirements = read("requirements.txt");

for (const forbidden of ["BoundedReviewChatModel", "scripted", "fake", "dummy", "simulated"]) {
  assert(!deepagents.toLowerCase().includes(forbidden.toLowerCase()), `DeepAgents runner contains forbidden fake marker: ${forbidden}`);
}

assert(deepagents.includes("OpenAICompatibleToolChatModel"), "DeepAgents must use a real OpenAI-compatible tool-calling chat model");
assert(deepagents.includes("DeepAgents completed without real tool calls"), "DeepAgents must reject runs with no real tool calls");
assert(deepagents.includes("trace_callback") && deepagents.includes("_trace_llm_call"), "DeepAgents LLM calls must be traced with request and response payloads");
assert(deepagents.includes("enable_stream") && deepagents.includes("collect_openai_sse_response"), "DeepAgents must support OpenAI-compatible SSE streaming");
assert(runExperts.includes("llm_trace=lambda fields: recorder.llm_call"), "Expert node must wire DeepAgents LLM traces into Recorder.llm_call");
assert(runtime.includes("subprocess.run("), "Static tools must be executed through subprocess.run");
assert(!runtime.includes('write_text("[]", "utf-8")'), "Static tool runner must not fabricate empty JSON reports");
assert(runtime.includes('status = "output_missing"'), "Static tool runner must mark missing reports as output_missing");
assert(runtime.includes("semgrep_config_args"), "Semgrep must be configured through OSS/project config args");
assert(runtime.includes("gitleaks_config_args"), "Gitleaks must be configured through OSS/project config args");
assert(runtime.includes("builtin_semgrep_configs"), "Semgrep must load built-in open-source rules");
assert(runtime.includes("builtin_pmd_rulesets"), "PMD must load built-in open-source rules");
assert(runtime.includes("custom_config_paths"), "Semgrep must support appending custom configs");
assert(runtime.includes("custom_rulesets"), "PMD must support appending custom rulesets");
assert(runtime.includes("extend_config_path"), "Gitleaks must support extending custom config");
assert(runtime.includes("builtin_java_heuristics_enabled"), "Built-in Java heuristics must be policy gated");
assert(runtime.includes("disabled_by_default_use_open_source_tools"), "Built-in Java heuristics must be disabled by default");
assert(runExperts.includes("legacy_static_heuristics_skipped"), "Expert node must skip legacy heuristics when project policy does not enable them");
assert(!seed.includes('tools: ["static.heuristic_prescan"]'), "Seeded experts must not bind legacy heuristic prescan by default");
assert(!agentRoutes.includes(': ["static.heuristic_prescan"]'), "Custom agent route must not default to legacy heuristic prescan");
assert(runtime.includes('"raw_reports"'), "Static tool raw report index must be captured");
assert(treeSitterTool.includes("from tree_sitter import Language, Parser"), "Tree-sitter tool must use the real Python tree_sitter parser");
assert(treeSitterTool.includes("tree_sitter_java"), "Tree-sitter Java grammar must be used");
assert(treeSitterTool.includes("parser.parse(source)"), "Tree-sitter tool must parse source through parser.parse");
assert(runtime.includes("static.tree_sitter_code_graph"), "Tree-sitter code graph must be recorded as a static tool call");
assert(requirements.includes("tree_sitter_java"), "requirements.txt must install tree-sitter Java grammar");

for (const tool of ["tree_sitter_code_graph", "semgrep", "gitleaks", "pmd", "checkstyle", "dependency-check", "osv-scanner", "trivy", "kics", "openapi-diff"]) {
  assert(runtime.includes(`"${tool}"`), `Missing static tool invocation for ${tool}`);
}

assert(prescan.includes("oss_static_toolchain_prescan"), "Prescan must use OSS static toolchain strategy");
assert(prescan.includes("open_source_tools_first"), "Toolchain manifest must mark OSS-first mode");
assert(!prescan.includes("mvp-heuristic-v1"), "Prescan must not use MVP heuristic version marker");
assert(!runExperts.includes("mvp-heuristic-v1"), "Expert node must not use MVP heuristic version marker");
assert(frontend.includes("模型服务配置"), "Settings page must expose model service form");
assert(frontend.includes("测试连接"), "Settings page must expose LLM connectivity test button");
assert(frontend.includes("启用 SSE 流式响应"), "Settings page must expose LLM SSE streaming toggle");
assert(frontend.includes("Math.min(600"), "Settings page must allow long LLM timeouts for Windows worker runs");
assert(frontend.includes("toolSave"), "Settings page must show static tool policy save feedback");
assert(frontend.includes("settings-success-modal"), "Settings page must show successful actions in a modal prompt");
assert(frontend.includes("settingsReady") && frontend.includes("SettingsConfigLoadingPanel"), "Settings page must not render default forms before real project config loads");
assert(frontend.includes("正在读取安装状态") && frontend.includes("tool-status-tag pending"), "Settings page must load static tool availability asynchronously without showing missing before checks finish");
assert(styles.includes(".llm-test-result") && styles.includes("overflow-wrap: anywhere"), "Settings failure messages must wrap long LLM test errors");
assert(styles.includes(".setting-form-card") && styles.includes("min-width: 0"), "Settings cards must be allowed to shrink inside CSS grid");
assert(!frontend.includes("JSON.stringify(item.value"), "Settings page must not expose raw JSON setting editor");
assert(projectRoutes.includes("/api/projects/:projectId/settings/llm/test"), "Backend must expose LLM test endpoint");
assert(projectRoutes.includes("compactLlmTestInput"), "LLM test endpoint must ignore blank fields instead of overriding saved credentials");
assert(projectRoutes.includes("stream_options") && projectRoutes.includes("parseOpenAiLikeResponse"), "LLM test endpoint must support SSE connectivity tests");
assert(projectRoutes.includes("Math.min(600"), "Backend LLM test must allow long LLM timeouts");

console.log(JSON.stringify({
  ok: true,
  checks: [
    "deepagents_real_model_guard",
    "no_fabricated_static_reports",
    "external_static_tools_invoked_by_subprocess",
    "oss_first_static_toolchain",
    "legacy_heuristic_prescan_not_default",
    "raw_static_tool_reports_recorded",
    "deepagents_llm_io_logged",
    "deepagents_sse_streaming_supported",
    "real_tree_sitter_parser_and_grammar_installed",
    "tree_sitter_code_graph_recorded_as_static_tool",
    "settings_form_without_json_editor",
    "llm_connectivity_test_endpoint",
    "settings_success_modal_prompt",
    "settings_real_config_loading_gate",
    "settings_static_tool_status_async",
    "settings_failure_message_wraps",
    "llm_sse_connectivity_test"
  ]
}, null, 2));
