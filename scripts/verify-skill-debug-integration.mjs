import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const postgresUrl = process.env.TEST_POSTGRES_URL || "";
if (!postgresUrl) {
  throw new Error("verify:skill-debug-integration requires TEST_POSTGRES_URL pointing to a disposable PostgreSQL database.");
}

const runId = `${process.pid}_${Date.now()}`;
const suffix = runId.replace(/[^a-zA-Z0-9]/g, "");
const tmpRoot = path.join(root, "data", "tmp", `skill-debug-integration-${runId}`);
const configPath = path.join(tmpRoot, "config.json");
const host = "127.0.0.1";
const commonPort = Number(process.env.SKILL_DEBUG_COMMON_PORT || 18122);
const mrPort = Number(process.env.SKILL_DEBUG_MR_PORT || 18123);
const internalToken = `skill-debug-integration-${suffix}`;
const adminPassword = "skill-debug-admin123";
const repoId = `repo_skill_debug_it_${suffix}`;
const mrId = `mr_skill_debug_it_${suffix}`;
const staleMrId = `mr_skill_debug_stale_it_${suffix}`;
const productionJobId = `job_skill_debug_prod_it_${suffix}`;
const reviewerUsername = `skill-debug-reviewer-${suffix}`.slice(0, 40);
const reviewerPassword = "reviewer123";

rmSync(tmpRoot, { recursive: true, force: true });
mkdirSync(tmpRoot, { recursive: true });
writeFileSync(configPath, JSON.stringify({
  llm: {
    default_provider: "dashscope-openai-compatible",
    default_base_url: "http://127.0.0.1:9/v1",
    default_model: "skill-debug-integration-model",
    default_api_key: "integration-placeholder-key",
    default_api_key_env: null,
    request_timeout_seconds: 1,
    max_output_tokens: 512,
    enable_stream: false
  },
  server: {
    host,
    common_port: commonPort,
    mr_port: mrPort,
    database_driver: "postgres",
    postgres_url: postgresUrl,
    postgres_user: process.env.TEST_POSTGRES_USER || "",
    postgres_password: process.env.TEST_POSTGRES_PASSWORD || "",
    postgres_query_timeout_seconds: 30
  },
  queue_policy: {
    poll_interval_seconds: 300,
    max_concurrency: 1,
    max_attempts: 1,
    heartbeat_timeout_seconds: 120,
    worker_pool_size: 1,
    max_worker_pool_size: 1,
    worker_reconcile_seconds: 30
  },
  skill_debug_policy: {
    project_max_concurrency: 2,
    user_max_concurrency: 2,
    daily_session_limit: 20,
    daily_token_limit: 1000000,
    max_duration_seconds: 300,
    retention_days: 1
  },
  logging: { enabled: false }
}, null, 2), "utf8");

function run(command, args, extraEnv = {}) {
  const result = spawnSync(command, args, {
    cwd: root,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, ...extraEnv }
  });
  if (result.status !== 0) throw new Error(`${command} ${args.join(" ")} failed\n${result.stdout}\n${result.stderr}`);
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function request(base, pathname, { method = "GET", body, token } = {}) {
  const response = await fetch(`${base}${pathname}`, {
    method,
    headers: {
      ...(body === undefined ? {} : { "content-type": "application/json" }),
      ...(token ? { authorization: `Bearer ${token}` } : {})
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) })
  });
  let json = {};
  try { json = await response.json(); } catch { json = {}; }
  return { status: response.status, json };
}

async function waitFor(base, pathname, predicate, token, attempts = 180) {
  let latest;
  for (let index = 0; index < attempts; index += 1) {
    try {
      latest = await request(base, pathname, { token });
      if (latest.status === 200 && predicate(latest.json)) return latest.json;
    } catch (error) {
      latest = { error: error instanceof Error ? error.message : String(error) };
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Timed out waiting for ${pathname}: ${JSON.stringify(latest)}`);
}

run("npm", ["--prefix", "common-backend", "run", "build"]);
run("npm", ["--prefix", "mr-backend", "run", "build"]);
process.env.CONFIG_PATH = configPath;
process.env.JOLT_INTERNAL_SERVICE_TOKEN = internalToken;
process.env.JOLT_LOCAL_ADMIN_PASSWORD = adminPassword;
process.env.JOLT_SEED_DEV_DATA = "1";

const commonDbModule = await import("../common-backend/build/backend/db.js");
const commonConfigModule = await import("../common-backend/build/backend/config.js");
const commonDb = commonDbModule.openDatabase(commonConfigModule.loadConfig());
const adminSalt = `skill-debug-integration-salt-${suffix}`;
const expectedAdminHash = createHash("sha256").update(`${adminSalt}:${adminPassword}`).digest("hex");
const adminUpdate = commonDb.prepare("UPDATE users SET password_hash=$1, password_salt=$2 WHERE id='user_local_admin'").run(expectedAdminHash, adminSalt);
const seededAdmin = commonDb.prepare("SELECT password_hash, password_salt FROM users WHERE id='user_local_admin'").get();
assert(seededAdmin?.password_hash === expectedAdminHash, `seeded root password mismatch (updated=${adminUpdate.changes}, row=${Boolean(seededAdmin)})`);
commonDb.close?.();

const mrDbModule = await import("../mr-backend/build/backend/db.js");
const mrConfigModule = await import("../mr-backend/build/backend/config.js");
const db = mrDbModule.openDatabase(mrConfigModule.loadConfig());
db.prepare(`
  INSERT INTO repositories (id, project_id, provider, external_repo_id, name, default_branch, status, provider_config_json)
  VALUES ($1, 'project_default', 'github', $2, $3, 'main', 'active', '{}')
`).run(repoId, `local/skill-debug-integration-${suffix}`, `skill-debug-integration-${suffix}`);
for (const [id, externalId, number, title, headSha] of [
  [mrId, `it-main-${suffix}`, 9101, "Skill debug integration main", `head-main-${suffix}`],
  [staleMrId, `it-stale-${suffix}`, 9102, "Skill debug integration stale", `head-stale-${suffix}`]
]) {
  db.prepare(`
    INSERT INTO merge_requests (
      id, repository_id, external_mr_id, number, title, author, source_branch,
      target_branch, review_status, risk_score, latest_head_sha, html_url, metadata_json
    ) VALUES ($1, $2, $3, $4, $5, 'integration', 'feature/skill-debug', 'main', 'no_issue', 10, $6, $7, '{}')
  `).run(id, repoId, externalId, number, title, headSha, `http://127.0.0.1/${externalId}`);
}
db.prepare(`
  INSERT INTO review_jobs (id, merge_request_id, head_sha, status, requested_by, execution_kind)
  VALUES ($1, $2, $3, 'no_issue', 'user_local_admin', 'production_review')
`).run(productionJobId, mrId, `head-main-${suffix}`);

const beforeMr = db.prepare("SELECT review_status, latest_head_sha FROM merge_requests WHERE id=$1").get(mrId);
const beforeProductionJob = db.prepare("SELECT id, status, head_sha FROM review_jobs WHERE id=$1").get(productionJobId);
const beforeHistory = Number(db.prepare("SELECT COUNT(*) AS count FROM mr_finding_history WHERE merge_request_id=$1").get(mrId)?.count || 0);
const originalSkill = db.prepare("SELECT content FROM custom_skill_versions WHERE project_id='project_default' AND skill_key='java-low-level-defect-review' AND version='v1'").get();
assert(originalSkill?.content, "seeded java-low-level-defect-review v1 is required");

const env = {
  ...process.env,
  CONFIG_PATH: configPath,
  JOLT_INTERNAL_SERVICE_TOKEN: internalToken,
  JOLT_LOCAL_ADMIN_PASSWORD: adminPassword,
  JOLT_SEED_DEV_DATA: "1",
  MR_WORKER_COUNT: "1",
  MR_WORKER_MAX: "1"
};
const children = [];
const output = [];
function start(entrypoint) {
  const child = spawn(process.execPath, [entrypoint], { cwd: root, env, stdio: ["ignore", "pipe", "pipe"] });
  children.push(child);
  child.stdout.on("data", (chunk) => output.push(String(chunk)));
  child.stderr.on("data", (chunk) => output.push(String(chunk)));
}

const commonBase = `http://${host}:${commonPort}`;
const mrBase = `http://${host}:${mrPort}`;
try {
  start("common-backend/build/backend/common-server.js");
  await waitFor(commonBase, "/api/health", (json) => json.service === "jolt-common-backend");
  start("mr-backend/build/backend/mr-server.js");
  await waitFor(mrBase, "/api/health", (json) => json.service === "jolt-mr-backend");

  const adminLogin = await request(commonBase, "/api/auth/login", { method: "POST", body: { username: "local-admin", password: adminPassword } });
  assert(adminLogin.status === 200, `admin login failed: ${adminLogin.status}`);
  const adminToken = adminLogin.json.token;
  const registration = await request(commonBase, "/api/auth/register", { method: "POST", body: { username: reviewerUsername, password: reviewerPassword, display_name: "Skill Debug Integration Reviewer" } });
  assert(registration.status === 200, `reviewer registration failed: ${registration.status}`);
  const reviewerLogin = await request(commonBase, "/api/auth/login", { method: "POST", body: { username: reviewerUsername, password: reviewerPassword } });
  assert(reviewerLogin.status === 200, `reviewer login failed: ${reviewerLogin.status}`);
  const reviewerToken = reviewerLogin.json.token;
  const invitation = await request(commonBase, "/api/projects/project_default/invitations", { method: "POST", token: adminToken, body: { role: "reviewer" } });
  assert(invitation.status === 200, `reviewer invitation failed: ${invitation.status}`);
  const join = await request(commonBase, "/api/projects/join-by-invite", { method: "POST", token: reviewerToken, body: { invite_code: invitation.json.invite_code } });
  assert(join.status === 200, `reviewer join failed: ${join.status}`);

  const createBody = { skill_key: "java-low-level-defect-review", skill_version: "v1", agent_key: "low_level_defect_agent", mode: "targeted", effort_level: "standard" };
  const first = await request(mrBase, "/api/mr-review/projects/project_default/skill-debug-sessions", { method: "POST", token: adminToken, body: { ...createBody, mr_id: mrId } });
  assert(first.status === 200, `first debug session failed: ${first.status} ${JSON.stringify(first.json)}`);
  const firstId = first.json.session.id;
  const firstSnapshotHash = first.json.session.snapshot_sha256;

  const stale = await request(mrBase, "/api/mr-review/projects/project_default/skill-debug-sessions", { method: "POST", token: adminToken, body: { ...createBody, mr_id: staleMrId } });
  assert(stale.status === 200, `stale debug session creation failed: ${stale.status}`);
  const staleId = stale.json.session.id;
  db.prepare("UPDATE merge_requests SET latest_head_sha=$1, updated_at=CURRENT_TIMESTAMP WHERE id=$2").run(`head-stale-changed-${suffix}`, staleMrId);

  const quota = await request(mrBase, "/api/mr-review/projects/project_default/skill-debug-sessions", { method: "POST", token: adminToken, body: { ...createBody, mr_id: mrId } });
  assert(quota.status === 429, `third active session must hit concurrency quota, got ${quota.status}`);

  const reviewerPaths = [
    ["GET", "/api/mr-review/projects/project_default/skill-debug-sessions"],
    ["POST", `/api/mr-review/projects/project_default/skill-debug-sessions`, { ...createBody, mr_id: mrId }],
    ["GET", `/api/mr-review/skill-debug-sessions/${firstId}`],
    ["POST", `/api/mr-review/skill-debug-sessions/${firstId}/cancel`, {}],
    ["POST", `/api/mr-review/skill-debug-sessions/${firstId}/rerun`, {}],
    ["GET", `/api/mr-review/skill-debug-sessions/${firstId}/export`]
  ];
  for (const [method, pathname, body] of reviewerPaths) {
    const denied = await request(mrBase, pathname, { method, token: reviewerToken, ...(body === undefined ? {} : { body }) });
    assert(denied.status === 403, `reviewer must get 403 for ${method} ${pathname}, got ${denied.status}`);
  }

  await request(mrBase, "/api/projects/project_default/custom-skills", {
    method: "POST",
    token: adminToken,
    body: {
      skill_key: "java-low-level-defect-review",
      name: "Java low-level defect integration draft",
      description: "integration draft must not mutate the frozen v1 snapshot",
      content: `${originalSkill.content}\n\nIntegration draft ${suffix}`,
      version: `v-it-${suffix}`,
      status: "draft"
    }
  });

  const terminalFirst = await waitFor(
    mrBase,
    `/api/mr-review/skill-debug-sessions/${firstId}`,
    (json) => ["completed", "degraded", "inconclusive"].includes(String(json.session?.status || "")),
    adminToken
  );
  assert(terminalFirst.session.snapshot_sha256 === firstSnapshotHash, "Skill edit changed the frozen session snapshot");
  assert(terminalFirst.baseline?.job?.id !== terminalFirst.candidate?.job?.id, "baseline and candidate must use different jobs");
  assert(terminalFirst.diagnostics?.baseline?.skill_loaded === false, "baseline must not report the target Skill as loaded");
  assert(terminalFirst.diagnostics?.candidate?.skill_loaded === true, "candidate must report the target Skill as loaded");
  assert(terminalFirst.session.status === "degraded", `unreachable VCS/LLM fixture must be degraded, got ${terminalFirst.session.status}`);
  assert(terminalFirst.validity?.conclusive === false, "degraded fixture must not be conclusive");
  assert(Array.isArray(terminalFirst.validity?.reasons) && terminalFirst.validity.reasons.length > 0, "degraded fixture must explain validity reasons");

  const staleDetail = await waitFor(mrBase, `/api/mr-review/skill-debug-sessions/${staleId}`, (json) => json.session?.status === "stale_head", adminToken);
  assert(staleDetail.session.failure_reason === "mr_head_changed", "stale head reason is not visible");

  const second = await request(mrBase, "/api/mr-review/projects/project_default/skill-debug-sessions", { method: "POST", token: adminToken, body: { ...createBody, mr_id: mrId } });
  assert(second.status === 200, `second same-SHA session failed: ${second.status}`);
  assert(second.json.session.id !== firstId, "same MR/SHA debug session must have a new session id");
  assert(second.json.baseline?.job?.id !== terminalFirst.baseline?.job?.id, "same MR/SHA baseline job was reused");
  assert(second.json.candidate?.job?.id !== terminalFirst.candidate?.job?.id, "same MR/SHA candidate job was reused");
  const cancelled = await request(mrBase, `/api/mr-review/skill-debug-sessions/${second.json.session.id}/cancel`, { method: "POST", token: adminToken, body: {} });
  assert(cancelled.status === 200 && cancelled.json.session?.status === "cancelled", "cancelled status is not visible");

  const rerun = await request(mrBase, `/api/mr-review/skill-debug-sessions/${firstId}/rerun`, { method: "POST", token: adminToken, body: {} });
  if (terminalFirst.session.input_artifact_sha256) {
    assert(rerun.status === 200, `snapshot rerun failed: ${rerun.status}`);
    assert(rerun.json.session.snapshot_sha256 === firstSnapshotHash, "rerun did not preserve the frozen snapshot hash");
    await request(mrBase, `/api/mr-review/skill-debug-sessions/${rerun.json.session.id}/cancel`, { method: "POST", token: adminToken, body: {} });
  } else {
    assert(rerun.status === 400, `rerun without a frozen input artifact must be rejected, got ${rerun.status}`);
  }

  const debugRunId = terminalFirst.candidate?.run?.id;
  assert(debugRunId, "terminal candidate run is required for publish protection test");
  const debugFindingId = `finding_skill_debug_it_${suffix}`;
  db.prepare(`
    INSERT INTO review_findings (
      id, review_run_id, severity, confidence, agent_id, head_sha, dedupe_hash,
      file_path, line_start, line_end, title, problem_description, recommendation, evidence
    ) VALUES ($1, $2, 'medium', 0.9, 'low_level_defect_agent', $3, $4, 'Demo.java', 1, 1,
      'debug finding', 'debug finding must not publish', 'run a production review', 'integration evidence')
  `).run(debugFindingId, debugRunId, `head-main-${suffix}`, `dedupe-${suffix}`);
  const publishBlocked = await request(mrBase, `/api/mr-review/merge-requests/${mrId}/publish`, { method: "POST", token: adminToken, body: { finding_ids: [debugFindingId], dry_run: true } });
  assert(publishBlocked.status === 409 && publishBlocked.json.error === "skill_debug.publish_forbidden", `debug finding publish guard failed: ${publishBlocked.status}`);

  const afterMr = db.prepare("SELECT review_status, latest_head_sha FROM merge_requests WHERE id=$1").get(mrId);
  const afterProductionJob = db.prepare("SELECT id, status, head_sha FROM review_jobs WHERE id=$1").get(productionJobId);
  const afterHistory = Number(db.prepare("SELECT COUNT(*) AS count FROM mr_finding_history WHERE merge_request_id=$1").get(mrId)?.count || 0);
  assert(JSON.stringify(afterMr) === JSON.stringify(beforeMr), "debug completion changed formal MR state");
  assert(JSON.stringify(afterProductionJob) === JSON.stringify(beforeProductionJob), "debug completion changed the production job");
  assert(afterHistory === beforeHistory, "debug completion changed formal finding history");

  console.log(JSON.stringify({
    ok: true,
    verified: "skill_debug_postgres_integration",
    reviewer_forbidden_routes: reviewerPaths.length,
    first_session: firstId,
    stale_session: staleId,
    production_job_unchanged: productionJobId,
    snapshot_sha256: firstSnapshotHash
  }, null, 2));
} finally {
  for (const child of children) if (!child.killed) child.kill();
  await new Promise((resolve) => setTimeout(resolve, 250));
  db.close?.();
  rmSync(tmpRoot, { recursive: true, force: true });
  if (process.env.DEBUG_SKILL_DEBUG_INTEGRATION) console.error(output.join(""));
}
