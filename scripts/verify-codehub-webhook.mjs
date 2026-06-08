import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { DatabaseSync } from "node:sqlite";
import { loadConfig, root } from "./config-utils.mjs";

const API = process.env.API_BASE || "http://127.0.0.1:8011";
const PROJECT_ID = process.env.PROJECT_ID || "project_default";

async function request(route, init) {
  const response = await fetch(`${API}${route}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    }
  });
  const json = await response.json();
  if (!response.ok) throw new Error(`${route} failed: ${JSON.stringify(json)}`);
  return json;
}

function dbPath() {
  const config = loadConfig();
  return path.resolve(root, config.server?.database_path || "data/jolt-codereview.sqlite");
}

function createFixtureFile() {
  const fixtureDir = path.join(root, "data", "fixtures");
  mkdirSync(fixtureDir, { recursive: true });
  const fixturePath = path.join(fixtureDir, "codehub-vulnerable-mr-files.json");
  writeFileSync(
    fixturePath,
    JSON.stringify(
      [
        {
          filename: "services/payment/project_settings.py",
          status: "modified",
          additions: 6,
          deletions: 0,
          changes: 6,
          patch:
            "@@ -0,0 +1,6 @@\n" +
            "+def update_project_settings(payload):\n" +
            "+    password = \"codehub-demo-secret\"\n" +
            "+    return eval(payload.get(\"expression\", \"0\"))\n" +
            "+\n" +
            "+def audit_change():\n" +
            "+    return True\n"
        }
      ],
      null,
      2
    ),
    "utf8"
  );
  return fixturePath;
}

await request("/api/health");
const fixturePath = createFixtureFile();
await request(`/api/projects/${PROJECT_ID}/repositories`, {
  method: "POST",
  body: JSON.stringify({
    provider: "codehub",
    git_url: "https://codehub.internal.fixture/trade-platform/payment-service.git",
    name: "payment-service",
    default_branch: "master",
    provider_config: {
      endpoint: "https://codehub.internal.fixture",
      fixture_changed_files: path.relative(root, fixturePath)
    }
  })
});

const headSha = `codehub_fixture_${Date.now()}`;
const webhook = await request(`/api/webhooks/codehub/${PROJECT_ID}`, {
  method: "POST",
  body: JSON.stringify({
    action: "opened",
    repository: {
      path_with_namespace: "trade-platform/payment-service"
    },
    merge_request: {
      id: 8801,
      iid: 8801,
      title: "CodeHub fixture MR with security regression",
      source_branch: "feat/project-setting",
      target_branch: "master",
      head_sha: headSha,
      web_url: "https://codehub.internal.fixture/trade-platform/payment-service/merge_requests/8801",
      author: { username: "codehub-user" },
      additions: 6,
      deletions: 0,
      changed_files: 1
    }
  })
});
if (!webhook.job_created && !webhook.merge_request_id) {
  throw new Error(`CodeHub webhook did not create or locate MR: ${JSON.stringify(webhook)}`);
}

const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const worker = spawnSync(npmCommand, ["run", "worker:once"], {
  cwd: root,
  stdio: "pipe",
  encoding: "utf8",
  env: { ...process.env }
});
if (worker.status !== 0) {
  throw new Error(`worker failed:\n${worker.stdout}\n${worker.stderr}`);
}

const db = new DatabaseSync(dbPath());
const mr = db.prepare(`
  SELECT mr.*
  FROM merge_requests mr
  JOIN repositories r ON r.id = mr.repository_id
  WHERE r.provider = 'codehub' AND r.external_repo_id = 'https://codehub.internal.fixture/trade-platform/payment-service.git' AND mr.external_mr_id = '8801'
`).get();
if (!mr) throw new Error("CodeHub webhook MR was not persisted");
const run = db.prepare(`
  SELECT rr.*, COUNT(rf.id) AS finding_count
  FROM review_runs rr
  JOIN review_jobs rj ON rj.id = rr.review_job_id
  LEFT JOIN review_findings rf ON rf.review_run_id = rr.id
  WHERE rj.merge_request_id = ?
  GROUP BY rr.id
  ORDER BY finding_count DESC, rr.started_at DESC
  LIMIT 1
`).get(mr.id);
if (!run) throw new Error("CodeHub fixture MR has no review run");
const findings = db.prepare("SELECT * FROM review_findings WHERE review_run_id = ?").all(run.id);
const toolCalls = db.prepare(`
  SELECT t.*
  FROM tool_call_records t
  JOIN agent_trace_spans s ON s.id = t.span_id
  WHERE s.review_run_id = ?
`).all(run.id);
db.close();

if (findings.length < 2) throw new Error(`expected CodeHub fixture findings, got ${findings.length}`);
const manifest = JSON.parse(run.toolchain_manifest || "{}");
if (manifest.orchestration?.engine !== "langgraph") {
  throw new Error(`CodeHub fixture run did not use LangGraph orchestration: ${JSON.stringify(manifest.orchestration)}`);
}
if (!manifest.orchestration?.langgraph_version) {
  throw new Error(`CodeHub fixture run did not record LangGraph version: ${JSON.stringify(manifest.orchestration)}`);
}
if (!manifest.orchestration?.deepagents?.package_version) {
  throw new Error(`CodeHub fixture run did not record DeepAgents package version: ${JSON.stringify(manifest.orchestration)}`);
}
if (manifest.orchestration?.deepagents?.sub_agents !== "disabled") {
  throw new Error(`CodeHub fixture run did not enforce bounded DeepAgents mode: ${JSON.stringify(manifest.orchestration.deepagents)}`);
}
if (!toolCalls.some((call) => String(call.tool_name).startsWith("static."))) {
  throw new Error("CodeHub fixture run has no static tool calls");
}

console.log(JSON.stringify({
  webhook,
  merge_request: {
    id: mr.id,
    title: mr.title,
    status: mr.review_status,
    head_sha: mr.latest_head_sha
  },
  run: {
    id: run.id,
    status: run.status,
    effort: run.effort_level,
    orchestration: manifest.orchestration
  },
  findings: findings.map((finding) => ({
    severity: finding.severity,
    agent_id: finding.agent_id,
    title: finding.title
  })),
  static_tool_calls: toolCalls.filter((call) => String(call.tool_name).startsWith("static.")).length
}, null, 2));
