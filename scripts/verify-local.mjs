import { authenticatedRequest, authHeaders, request } from "./api-auth.mjs";

const PROJECT_ID = process.env.PROJECT_ID || "project_default";

const health = await request("/api/health");
const headers = await authHeaders();
const session = await request("/api/auth/session", {
  headers
});
const repos = await authenticatedRequest(`/api/projects/${PROJECT_ID}/repositories`);
const members = await authenticatedRequest(`/api/projects/${PROJECT_ID}/members`);
const ruleSets = await authenticatedRequest(`/api/projects/${PROJECT_ID}/rule-sets`);
const agents = await authenticatedRequest(`/api/projects/${PROJECT_ID}/agents`);
const reviewPolicy = await authenticatedRequest(`/api/projects/${PROJECT_ID}/review-policy`);
const fullReview = await authenticatedRequest(`/api/full-review/projects/${PROJECT_ID}/jobs`);
const deadLetters = await authenticatedRequest(`/api/mr-review/projects/${PROJECT_ID}/dead-letters`);
const auditLogs = await authenticatedRequest(`/api/projects/${PROJECT_ID}/audit-logs`);
const quality = await authenticatedRequest(`/api/projects/${PROJECT_ID}/review-quality/summary`);
const evaluation = await authenticatedRequest(`/api/projects/${PROJECT_ID}/evaluation-reports`);
const ruleHealth = await authenticatedRequest(`/api/projects/${PROJECT_ID}/rule-health`);
const list = await authenticatedRequest(`/api/mr-review/projects/${PROJECT_ID}/merge-requests`);
const counts = list.items.reduce((acc, item) => {
  acc[item.review_status] = (acc[item.review_status] || 0) + 1;
  return acc;
}, {});

let detailSummary = null;
let reviewed = null;
let reviewedEvidence = null;
for (const candidate of list.items.filter((item) => item.review_status !== "queued")) {
  const detail = await authenticatedRequest(`/api/mr-review/merge-requests/${candidate.id}`);
  const latestRunId = detail.runs[0]?.id;
  const logs = latestRunId ? await authenticatedRequest(`/api/mr-review/review-runs/${latestRunId}/session-logs`) : null;
  const artifacts = latestRunId ? await authenticatedRequest(`/api/mr-review/review-runs/${latestRunId}/artifacts`) : null;
  const runDetail = latestRunId ? await authenticatedRequest(`/api/mr-review/review-runs/${latestRunId}`) : null;
  const compare = await authenticatedRequest(`/api/mr-review/merge-requests/${candidate.id}/review-runs/compare`);
  const manifest = runDetail?.toolchain_manifest ? JSON.parse(runDetail.toolchain_manifest) : {};
  const artifactNames = artifacts?.items?.map((artifact) => artifact.name) ?? [];
  detailSummary = {
    mr_id: candidate.id,
    status: candidate.review_status,
    runs: detail.runs.length,
    latest_run_status: runDetail?.status,
    latest_run_effort: runDetail?.effort_level,
    orchestration: manifest.orchestration ?? null,
    toolchain_static: manifest.static ?? null,
    findings: detail.findings.length,
    trace_events: detail.trace.length,
    agent_messages: logs?.messages?.length ?? 0,
    llm_calls: logs?.llm_calls?.length ?? 0,
    tool_calls: logs?.tool_calls?.length ?? 0,
    artifacts: artifacts?.items?.length ?? 0,
    compare_shape: Object.keys(compare).sort()
  };
  if (
    logs?.messages?.length &&
    logs?.tool_calls?.length &&
    logs?.llm_calls?.length &&
    artifacts?.items?.length &&
    manifest.static?.external?.tools?.length &&
    artifactNames.includes("static_tool_results.json")
  ) {
    reviewed = candidate;
    reviewedEvidence = { detail, logs, artifacts };
    break;
  }
}
if (detailSummary) {
  if (!reviewedEvidence) {
    throw new Error("no reviewed MR has complete session logs, tool calls, llm calls and artifacts");
  }
  if (reviewedEvidence.detail.runs.length === 0) {
    throw new Error("reviewed MR has no review run");
  }
  if (reviewedEvidence.detail.trace.length === 0) {
    throw new Error("reviewed MR has no trace events");
  }
  if (!reviewedEvidence.logs || reviewedEvidence.logs.tool_calls.length === 0) {
    throw new Error("reviewed MR has no tool call records");
  }
  if (!reviewedEvidence.logs || reviewedEvidence.logs.llm_calls.length === 0) {
    throw new Error("reviewed MR has no llm call records");
  }
  if (!reviewedEvidence.logs || reviewedEvidence.logs.messages.length === 0) {
    throw new Error("reviewed MR has no agent messages");
  }
  if (!reviewedEvidence.logs.events.some((event) => event.event_type === "agent_profile_loaded")) {
    throw new Error("reviewed MR has no expert profile trace events");
  }
  if (!reviewedEvidence.logs.messages.some((message) => String(message.content_summary || "").includes("按规范逐条检视"))) {
    throw new Error("reviewed MR did not instruct agents to review markdown rules item by item");
  }
  if (!reviewedEvidence.artifacts || reviewedEvidence.artifacts.items.length === 0) {
    throw new Error("reviewed MR has no review artifacts");
  }
  const runDetail = await authenticatedRequest(`/api/mr-review/review-runs/${reviewedEvidence.detail.runs[0].id}`);
  const manifest = JSON.parse(runDetail.toolchain_manifest || "{}");
  if (!manifest.static?.external?.tools?.length) {
    throw new Error("reviewed MR has no external static toolchain manifest");
  }
  if (manifest.orchestration?.engine !== "langgraph") {
    throw new Error(`reviewed MR was not orchestrated by LangGraph: ${JSON.stringify(manifest.orchestration)}`);
  }
  if (!manifest.orchestration?.langgraph_version) {
    throw new Error(`reviewed MR did not record LangGraph version: ${JSON.stringify(manifest.orchestration)}`);
  }
  if (!manifest.orchestration?.deepagents?.package_version) {
    throw new Error(`reviewed MR did not record DeepAgents package version: ${JSON.stringify(manifest.orchestration)}`);
  }
  if (manifest.orchestration?.deepagents?.sub_agents !== "disabled") {
    throw new Error(`reviewed MR did not enforce bounded DeepAgents mode: ${JSON.stringify(manifest.orchestration.deepagents)}`);
  }
  const artifactNames = reviewedEvidence.artifacts.items.map((artifact) => artifact.name);
  if (!artifactNames.includes("static_tool_results.json")) {
    throw new Error("reviewed MR has no static_tool_results artifact");
  }
}

if (!health.ok) throw new Error("health check failed");
if (!session.authenticated) throw new Error("auth session check failed");
if (!repos.length) throw new Error("no repository bound");
if (!members.length) throw new Error("no project members");
if (!ruleSets.length) throw new Error("no rule sets");
if (!agents.length) throw new Error("no agent configs");
if (!reviewPolicy?.policy_json) throw new Error("no review policy");
if (!Array.isArray(fullReview.items)) throw new Error("full review job API failed");
if (!Array.isArray(deadLetters.items)) throw new Error("dead letter API failed");
if (!Array.isArray(auditLogs.items) || auditLogs.items.length === 0) throw new Error("audit log API has no records");
if (!quality.llm_calls) throw new Error("review quality API failed");
if (!Array.isArray(evaluation.items) || !evaluation.items.length) throw new Error("evaluation report API failed");
if (!Array.isArray(ruleHealth.items)) throw new Error("rule health API failed");
if (!list.items.length) throw new Error("no merge requests synced");

console.log(JSON.stringify({
  health,
  auth: {
    user: session.user?.username,
    token: "authenticated"
  },
  repositories: repos.map((repo) => ({
    provider: repo.provider,
    external_repo_id: repo.external_repo_id
  })),
  members: members.length,
  rule_sets: ruleSets.length,
  agents: agents.map((agent) => agent.agent_id),
  review_policy: JSON.parse(reviewPolicy.policy_json),
  full_review_status: fullReview.status,
  dead_letters: deadLetters.items.length,
  audit_logs: auditLogs.items.length,
  quality,
  evaluation: evaluation.items[0],
  rule_health_count: ruleHealth.items.length,
  mr_count: list.items.length,
  status_counts: counts,
  reviewed: detailSummary
}, null, 2));
