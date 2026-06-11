import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import { DatabaseSync } from "node:sqlite";
import { authenticatedRequest, request } from "./api-auth.mjs";
import { loadConfig, root } from "./config-utils.mjs";

const PROJECT_ID = process.env.PROJECT_ID || "project_default";

function id(prefix) {
  return `${prefix}_${randomUUID().replace(/-/g, "").slice(0, 16)}`;
}

function dbPath() {
  const config = loadConfig();
  return path.resolve(root, config.server?.database_path || "data/jolt-codereview.sqlite");
}

function createFixtureReview() {
  const fixtureDir = path.join(root, "data", "fixtures");
  mkdirSync(fixtureDir, { recursive: true });
  const fixturePath = path.join(fixtureDir, "github-vulnerable-pr-files.json");
  writeFileSync(
    fixturePath,
    JSON.stringify(
      [
        {
          filename: "backend/api/project.py",
          status: "modified",
          additions: 7,
          deletions: 0,
          changes: 7,
          patch:
            "@@ -0,0 +1,7 @@\n" +
            "+def update_project_settings(payload):\n" +
            "+    password = \"plain-text-demo-secret\"\n" +
            "+    return eval(payload.get(\"expression\", \"0\"))\n" +
            "+\n" +
            "+def handle_request():\n" +
            "+    try:\n" +
            "+        update_project_settings({})\n"
        }
      ],
      null,
      2
    ),
    "utf8"
  );

  const db = new DatabaseSync(dbPath());
  const repoId = "repo_github_fixture";
  const mrId = `mr_${repoId}_9001`;
  const headSha = `fixture_${Date.now()}`;
  const jobId = id("job");
  const providerConfig = {
    endpoint: "https://api.github.com",
    owner: "jolt-fixture",
    repo: "vulnerable-service",
    token_env: "GITHUB_TOKEN",
    fixture_changed_files: path.relative(root, fixturePath)
  };

  db.prepare(`
    INSERT INTO repositories (id, project_id, provider, external_repo_id, name, default_branch, status, provider_config_json)
    VALUES (?, ?, 'github', 'jolt-fixture/vulnerable-service', 'vulnerable-service', 'main', 'active', ?)
    ON CONFLICT(project_id, provider, external_repo_id) DO UPDATE SET
      name = excluded.name,
      status = 'active',
      provider_config_json = excluded.provider_config_json,
      updated_at = CURRENT_TIMESTAMP
  `).run(repoId, PROJECT_ID, JSON.stringify(providerConfig));

  db.prepare(`
    INSERT INTO merge_requests (
      id, repository_id, external_mr_id, number, title, author, source_branch, target_branch,
      review_status, risk_score, latest_head_sha, html_url, metadata_json, updated_at
    )
    VALUES (?, ?, '9001', 9001, 'Fixture PR with security regression', 'fixture-user', 'feature/security-regression', 'main',
      'queued', 96, ?, 'https://github.com/jolt-fixture/vulnerable-service/pull/9001', ?, CURRENT_TIMESTAMP)
    ON CONFLICT(repository_id, external_mr_id) DO UPDATE SET
      review_status = 'queued',
      risk_score = excluded.risk_score,
      latest_head_sha = excluded.latest_head_sha,
      metadata_json = excluded.metadata_json,
      updated_at = CURRENT_TIMESTAMP
  `).run(
    mrId,
    repoId,
    headSha,
    JSON.stringify({ provider: "github", fixture: true, changed_files: 1, additions: 7, deletions: 0 })
  );

  db.prepare("UPDATE review_jobs SET status = 'superseded', updated_at = CURRENT_TIMESTAMP WHERE merge_request_id = ? AND status = 'queued'")
    .run(mrId);
  db.prepare(`
    INSERT INTO review_jobs (id, merge_request_id, head_sha, status, priority, requested_effort_level)
    VALUES (?, ?, ?, 'queued', 999, 'standard')
  `).run(jobId, mrId, headSha);
  db.close();
  return { mrId, jobId, headSha, fixturePath };
}

await request("/api/health");
const fixture = createFixtureReview();
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

const detail = await authenticatedRequest(`/api/mr-review/merge-requests/${fixture.mrId}`);
const latestRun = detail.runs[0];
if (!latestRun) throw new Error("fixture MR has no review run");
if (detail.findings.length < 2) {
  throw new Error(`expected at least 2 findings, got ${detail.findings.length}`);
}
const selectedFindingIds = detail.findings.filter((finding) => finding.selected).map((finding) => finding.id);
if (selectedFindingIds.length < 2) throw new Error("fixture findings were not selected for publish");

const logs = await authenticatedRequest(`/api/mr-review/review-runs/${latestRun.id}/session-logs`);
const artifacts = await authenticatedRequest(`/api/mr-review/review-runs/${latestRun.id}/artifacts`);
const runDetail = await authenticatedRequest(`/api/mr-review/review-runs/${latestRun.id}`);
if (!logs.tool_calls.length || !logs.llm_calls.length || !logs.messages.length) {
  throw new Error("fixture run does not have complete session logs");
}
if (!logs.events.some((event) => event.event_type === "agent_profile_loaded")) {
  throw new Error("fixture run did not record expert agent profile loading");
}
if (!logs.messages.some((message) => String(message.content_summary || "").includes("按规范逐条检视"))) {
  throw new Error("fixture run did not instruct agents to review markdown rules item by item");
}
if (!artifacts.items.length) throw new Error("fixture run has no artifacts");
const manifest = JSON.parse(runDetail.toolchain_manifest || "{}");
if (!manifest.static?.external?.tools?.length) {
  throw new Error("fixture run has no external static toolchain manifest");
}
if (manifest.orchestration?.engine !== "langgraph") {
  throw new Error(`fixture run did not use LangGraph orchestration: ${JSON.stringify(manifest.orchestration)}`);
}
if (!manifest.orchestration?.langgraph_version) {
  throw new Error(`fixture run did not record LangGraph version: ${JSON.stringify(manifest.orchestration)}`);
}
if (!manifest.orchestration?.deepagents?.package_version) {
  throw new Error(`fixture run did not record DeepAgents package version: ${JSON.stringify(manifest.orchestration)}`);
}
if (manifest.orchestration?.deepagents?.sub_agents !== "disabled") {
  throw new Error(`fixture run did not enforce bounded DeepAgents mode: ${JSON.stringify(manifest.orchestration.deepagents)}`);
}
const artifactNames = artifacts.items.map((artifact) => artifact.name);
if (!artifactNames.includes("static_tool_results.json")) {
  throw new Error("fixture run has no static_tool_results artifact");
}

const publish = await authenticatedRequest(`/api/mr-review/merge-requests/${fixture.mrId}/publish`, {
  method: "POST",
  body: JSON.stringify({ finding_ids: selectedFindingIds, dry_run: true })
});
if (publish.published_count !== selectedFindingIds.length || !publish.dry_run) {
  throw new Error("dry-run publish did not record all selected findings");
}

const feedback = await authenticatedRequest(`/api/mr-review/review-findings/${selectedFindingIds[0]}/feedback`, {
  method: "POST",
  body: JSON.stringify({ feedback_type: "false_positive", scope: "project", reason: "e2e verification feedback" })
});
if (feedback.lifecycle_state !== "false_positive") throw new Error("false-positive feedback was not persisted");

const afterPublish = await authenticatedRequest(`/api/mr-review/merge-requests/${fixture.mrId}`);
const accepted = afterPublish.findings.filter((finding) => finding.publish_state === "dry_run").length;
if (accepted < selectedFindingIds.length - 1) {
  throw new Error("publish states were not persisted after dry-run publish");
}

console.log(JSON.stringify({
  fixture,
  run: {
    id: latestRun.id,
    status: latestRun.status,
    effort: latestRun.effort_level
  },
  findings: detail.findings.map((finding) => ({
    severity: finding.severity,
    agent_id: finding.agent_id,
    title: finding.title,
    file_path: finding.file_path,
    selected: finding.selected
  })),
  logs: {
    spans: logs.spans.length,
    events: logs.events.length,
    messages: logs.messages.length,
    tool_calls: logs.tool_calls.length,
    llm_calls: logs.llm_calls.length,
    static_tools: manifest.static.external.tools.map((item) => ({
      tool: item.tool,
      status: item.status,
      available: item.available
    })),
    orchestration: manifest.orchestration
  },
  artifacts: artifacts.items.length,
  publish: {
    dry_run: publish.dry_run,
    published_count: publish.published_count,
    comment_ref: publish.comment_ref
  },
  feedback: {
    finding_id: feedback.id,
    lifecycle_state: feedback.lifecycle_state
  }
}, null, 2));
