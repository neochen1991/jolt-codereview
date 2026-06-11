import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

const API = process.env.API_BASE || "http://127.0.0.1:8011";
const PROJECT_ID = process.env.PROJECT_ID || "project_default";
const root = process.cwd();
const config = JSON.parse(readFileSync(path.resolve(root, process.env.CONFIG_PATH || "config.json"), "utf8"));

async function request(path, init) {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    }
  });
  const json = await response.json();
  if (!response.ok) {
    throw new Error(`${path} failed: ${JSON.stringify(json)}`);
  }
  return json;
}

function assertArray(value, label) {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  return value;
}

const health = await request("/api/health");
if (!health.ok) throw new Error("health check failed");

const login = await request("/api/auth/login", {
  method: "POST",
  body: JSON.stringify({
    username: process.env.JOLT_TEST_USERNAME || "local-admin",
    password: process.env.JOLT_TEST_PASSWORD || process.env.JOLT_LOCAL_ADMIN_PASSWORD || "admin123"
  })
});
if (!login.token) throw new Error("login did not return token");

const authHeaders = { Authorization: `Bearer ${login.token}` };
const me = await request("/api/me", { headers: authHeaders });
if (!me.user?.username) throw new Error("/api/me did not return a user");
if (!assertArray(me.projects, "me.projects").length) throw new Error("/api/me did not return projects");

const projects = await request("/api/projects", { headers: authHeaders });
if (!assertArray(projects, "projects").length) throw new Error("no projects returned");

const project = projects.find((item) => item.id === PROJECT_ID) ?? projects[0];
if (!project?.id) throw new Error("no active project found for baseline verification");
const projectId = project.id;

const repositories = await request(`/api/projects/${projectId}/repositories`, { headers: authHeaders });
if (!assertArray(repositories, "repositories").length) throw new Error("no repositories returned");

const sync = await request(`/api/mr-review/projects/${projectId}/sync`, {
  method: "POST",
  headers: authHeaders
});
if (typeof sync.repositories !== "number") throw new Error("sync response missing repository count");
if (!Array.isArray(sync.errors)) throw new Error("sync response missing errors array");

const mrList = await request(`/api/mr-review/projects/${projectId}/merge-requests`, { headers: authHeaders });
if (!Array.isArray(mrList.items)) throw new Error("MR list did not return items array");
if (!mrList.items.length) throw new Error("MR list is empty");

const firstMr = mrList.items[0];
const detail = await request(`/api/mr-review/merge-requests/${firstMr.id}`, { headers: authHeaders });
if (!detail.mr?.id) throw new Error("MR detail did not include mr");
if (!Array.isArray(detail.jobs)) throw new Error("MR detail did not include jobs");
if (!Array.isArray(detail.runs)) throw new Error("MR detail did not include runs");
if (!Array.isArray(detail.findings)) throw new Error("MR detail did not include findings");
if (!Array.isArray(detail.trace)) throw new Error("MR detail did not include trace");
if (!detail.session_logs) throw new Error("MR detail did not include session_logs");
for (const key of ["messages", "tool_calls", "llm_calls", "mcp_calls", "artifacts"]) {
  if (!Array.isArray(detail.session_logs[key])) throw new Error(`session_logs.${key} must be an array`);
}

const unifiedLogs = await request(`/api/mr-review/merge-requests/${firstMr.id}/logs`, { headers: authHeaders });
if (!unifiedLogs.mr_id) throw new Error("unified logs did not include mr_id");
if (!unifiedLogs.counts || typeof unifiedLogs.counts.tool_call !== "number") throw new Error("unified logs did not include counts");
if (!Array.isArray(unifiedLogs.items)) throw new Error("unified logs did not include items array");
if (detail.runs.length && !unifiedLogs.items.some((item) => item.kind === "tool_call")) throw new Error("unified logs missing tool_call items");
if (detail.runs.length && !unifiedLogs.items.some((item) => item.kind === "llm_call")) throw new Error("unified logs missing llm_call items");
if (detail.runs.length && !unifiedLogs.items.some((item) => item.kind === "trace_event")) throw new Error("unified logs missing trace_event items");
if (detail.runs.length && !unifiedLogs.items.some((item) => item.kind === "agent_message")) throw new Error("unified logs missing agent_message items");

const logDir = path.resolve(root, config.logging?.dir || "logs");
const apiLogPath = path.join(logDir, config.logging?.api_file || "jolt-api.log");
if (!existsSync(apiLogPath)) throw new Error(`api log file does not exist: ${apiLogPath}`);
const apiLogTail = readFileSync(apiLogPath, "utf8").split("\n").slice(-50).join("\n");
if (!apiLogTail.includes("\"event\":\"http_request\"")) throw new Error("api log file does not include http_request events");
if (!apiLogTail.includes(`/api/mr-review/merge-requests/${firstMr.id}/logs`)) throw new Error("api log file does not include unified logs request");

const quality = await request(`/api/projects/${projectId}/review-quality/summary`, { headers: authHeaders });
if (!quality.llm_calls || typeof quality.llm_calls.count !== "number") {
  throw new Error("review quality summary did not include llm call count");
}

console.log(JSON.stringify({
  ok: true,
  api: API,
  project_id: projectId,
  user: me.user.username,
  repositories: repositories.length,
  sync: {
    repositories: sync.repositories,
    merge_requests: sync.merge_requests,
    jobs_created: sync.jobs_created,
    errors: sync.errors.length
  },
  merge_requests: mrList.items.length,
  first_mr: {
    id: firstMr.id,
    provider: firstMr.provider,
    repository: firstMr.repository_name,
    status: firstMr.review_status,
    latest_run_count: detail.runs.length,
    finding_count: detail.findings.length,
    trace_events: detail.trace.length
  },
  session_logs: {
    messages: detail.session_logs.messages.length,
    tool_calls: detail.session_logs.tool_calls.length,
    llm_calls: detail.session_logs.llm_calls.length,
    mcp_calls: detail.session_logs.mcp_calls.length,
    artifacts: detail.session_logs.artifacts.length
  },
  unified_logs: {
    items: unifiedLogs.items.length,
    counts: unifiedLogs.counts
  },
  file_logs: {
    api_log: apiLogPath
  },
  quality: {
    llm_calls: quality.llm_calls.count,
    tool_calls: quality.tool_calls?.count ?? 0
  }
}, null, 2));
