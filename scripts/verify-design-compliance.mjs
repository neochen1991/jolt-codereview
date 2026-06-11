import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { authenticatedRequest } from "./api-auth.mjs";
import { loadConfig, root } from "./config-utils.mjs";

const PROJECT_ID = process.env.PROJECT_ID || "project_default";
const auditPath = path.join(root, "docs", "plans", "2026-06-06-design-implementation-audit.md");

function dbPath() {
  const config = loadConfig();
  return path.resolve(root, config.server?.database_path || "data/jolt-codereview.sqlite");
}

function tableColumns(db, table) {
  return new Set(db.prepare(`PRAGMA table_info(${table})`).all().map((row) => row.name));
}

function requireColumns(db, table, columns) {
  const existing = tableColumns(db, table);
  const missing = columns.filter((column) => !existing.has(column));
  if (missing.length) throw new Error(`${table} missing columns: ${missing.join(", ")}`);
}

function parseJson(value, label) {
  try {
    return JSON.parse(value || "{}");
  } catch {
    throw new Error(`${label} is not valid JSON`);
  }
}

if (!existsSync(auditPath)) {
  throw new Error(`implementation audit document is missing: ${auditPath}`);
}
const audit = readFileSync(auditPath, "utf8");
if (!audit.includes("总体状态：全部完成")) {
  throw new Error("implementation audit document does not mark overall status complete");
}
if (/未完成|待补|部分完成/.test(audit)) {
  throw new Error("implementation audit document still contains incomplete markers");
}

const db = new DatabaseSync(dbPath());

for (const table of [
  "users",
  "projects",
  "project_members",
  "repositories",
  "merge_requests",
  "review_jobs",
  "review_runs",
  "review_findings",
  "agent_trace_spans",
  "agent_trace_events",
  "agent_messages",
  "tool_call_records",
  "mcp_call_records",
  "llm_call_records",
  "review_artifacts",
  "code_index_snapshots",
  "agent_configs",
  "rule_sets",
  "review_policy",
  "user_feedback",
  "review_jobs_dead_letter",
  "webhook_dead_letter",
  "vcs_publish_records",
  "evaluation_gold_set",
  "evaluation_reports"
]) {
  const row = db.prepare("SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?").get(table);
  if (!row) throw new Error(`missing table ${table}`);
}

requireColumns(db, "review_runs", [
  "effort_level",
  "risk_score",
  "rule_version_source",
  "sandbox_uri",
  "budget_json",
  "budget_used_json",
  "toolchain_manifest",
  "data_policy_snapshot"
]);
requireColumns(db, "review_jobs", ["head_sha", "attempt", "heartbeat_at", "locked_at", "locked_by"]);
requireColumns(db, "review_findings", ["dedupe_hash", "publish_state", "lifecycle_state", "selected"]);

const agents = db.prepare("SELECT agent_id, enabled, applies_to_json, skills_json FROM agent_configs WHERE project_id = ?").all(PROJECT_ID);
const enabledAgents = agents.filter((agent) => agent.enabled === 1).map((agent) => agent.agent_id);
for (const agentId of ["performance_agent", "security_agent", "coding_agent", "ddd_agent", "frontend_agent", "test_agent", "redis_agent"]) {
  if (!enabledAgents.includes(agentId)) throw new Error(`prebuilt expert agent is not enabled: ${agentId}`);
}

const run = db.prepare(`
  SELECT rr.*
  FROM review_runs rr
  JOIN review_jobs rj ON rj.id = rr.review_job_id
  JOIN merge_requests mr ON mr.id = rj.merge_request_id
  JOIN repositories r ON r.id = mr.repository_id
  WHERE r.project_id = ?
  ORDER BY rr.started_at DESC
  LIMIT 1
`).get(PROJECT_ID);
if (!run) throw new Error("no review run available for design compliance check");
const budget = parseJson(run.budget_json, "budget_json");
const budgetUsed = parseJson(run.budget_used_json, "budget_used_json");
const manifest = parseJson(run.toolchain_manifest, "toolchain_manifest");
const dataPolicy = parseJson(run.data_policy_snapshot, "data_policy_snapshot");
if (!budget.max_input_tokens || !budget.max_wall_seconds || !budget.on_exceed) {
  throw new Error(`review budget is incomplete: ${JSON.stringify(budget)}`);
}
if (typeof budgetUsed.input_tokens !== "number" || typeof budgetUsed.llm_calls !== "number") {
  throw new Error(`review budget usage is incomplete: ${JSON.stringify(budgetUsed)}`);
}
if (!manifest.orchestration?.deepagents || !manifest.static?.external || !manifest.context?.code_context_service) {
  throw new Error(`toolchain manifest misses orchestration/static/context evidence: ${JSON.stringify(manifest)}`);
}
if (!dataPolicy.default_llm_provider || !dataPolicy.prompt_retention || !Array.isArray(dataPolicy.sensitive_paths)) {
  throw new Error(`data policy snapshot is incomplete: ${JSON.stringify(dataPolicy)}`);
}

db.close();

await authenticatedRequest("/api/me");
await authenticatedRequest(`/api/projects/${PROJECT_ID}/members`);
await authenticatedRequest(`/api/projects/${PROJECT_ID}/repositories`);
await authenticatedRequest(`/api/projects/${PROJECT_ID}/rule-sets`);
await authenticatedRequest(`/api/projects/${PROJECT_ID}/agents`);
await authenticatedRequest(`/api/projects/${PROJECT_ID}/review-policy`);
await authenticatedRequest(`/api/mr-review/projects/${PROJECT_ID}/merge-requests`);
await authenticatedRequest(`/api/full-review/projects/${PROJECT_ID}/jobs`);
await authenticatedRequest(`/api/projects/${PROJECT_ID}/review-quality/summary`);
await authenticatedRequest(`/api/projects/${PROJECT_ID}/evaluation-reports`);
await authenticatedRequest(`/api/projects/${PROJECT_ID}/rule-health`);

console.log(JSON.stringify({
  ok: true,
  audit: path.relative(root, auditPath),
  enabled_agents: enabledAgents,
  latest_run: {
    id: run.id,
    effort_level: run.effort_level,
    status: run.status,
    orchestration: manifest.orchestration?.engine,
    code_context_service: manifest.context?.code_context_service?.status,
    budget_used: budgetUsed
  }
}, null, 2));
