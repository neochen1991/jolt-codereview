import { randomBytes, randomUUID } from "node:crypto";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { Client } from "pg";

const root = path.resolve(import.meta.dirname, "..");
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const isWin = process.platform === "win32";

if (isWin) {
  throw new Error("verify:split-full-regression currently expects local PostgreSQL CLI tools on macOS/Linux.");
}

const keepTmp = process.env.KEEP_SPLIT_REGRESSION_TMP === "1";
const skipInstall = process.env.SPLIT_REGRESSION_SKIP_INSTALL === "1";
const tmpRoot = await mkdtemp(path.join(tmpdir(), "jolt-split-regression-"));
const pgData = path.join(tmpRoot, "pgdata");
const splitRoot = path.join(tmpRoot, "split-repos");
const pgPort = process.env.SPLIT_REGRESSION_PG_PORT
  ? Number(process.env.SPLIT_REGRESSION_PG_PORT)
  : await choosePortBlock(55432, 1);
const commonPort = process.env.SPLIT_REGRESSION_COMMON_PORT
  ? Number(process.env.SPLIT_REGRESSION_COMMON_PORT)
  : await choosePortBlock(18110, 3);
const mrPort = commonPort + 1;
const frontendPort = commonPort + 2;
const dbName = "jolt_split_regression";
const pgUrl = `postgresql://neochen@127.0.0.1:${pgPort}/${dbName}`;
const internalToken = `split-regression-${randomBytes(8).toString("hex")}`;
const children = [];
let pgStarted = false;

async function canListen(port) {
  return new Promise((resolve) => {
    const server = createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    server.listen(port, "127.0.0.1");
  });
}

async function choosePortBlock(start, count) {
  for (let base = start; base < start + 3000; base += count) {
    const checks = [];
    for (let offset = 0; offset < count; offset += 1) {
      checks.push(canListen(base + offset));
    }
    if ((await Promise.all(checks)).every(Boolean)) return base;
  }
  throw new Error(`Could not find ${count} free localhost ports starting at ${start}`);
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd ?? root,
    env: { ...process.env, ...(options.env ?? {}) },
    encoding: "utf8",
    stdio: options.stdio ?? ["ignore", "pipe", "pipe"],
    shell: false
  });
  if (result.status !== 0) {
    throw new Error([
      `${command} ${args.join(" ")} failed with exit ${result.status}`,
      result.stdout,
      result.stderr
    ].filter(Boolean).join("\n"));
  }
  return result.stdout;
}

function start(label, command, args, options = {}) {
  const child = spawn(command, args, {
    cwd: options.cwd ?? root,
    env: { ...process.env, ...(options.env ?? {}) },
    stdio: ["ignore", "pipe", "pipe"],
    shell: false
  });
  const output = [];
  child.stdout.on("data", (chunk) => output.push(String(chunk)));
  child.stderr.on("data", (chunk) => output.push(String(chunk)));
  child.on("exit", (code) => {
    if (code && !child.killed) {
      console.error(`${label} exited with code ${code}\n${output.join("")}`);
    }
  });
  children.push({ label, child, output });
  return { child, output };
}

async function stopChildren() {
  for (const item of children.reverse()) {
    if (!item.child.killed) item.child.kill("SIGINT");
  }
  await new Promise((resolve) => setTimeout(resolve, 500));
}

async function cleanup() {
  await stopChildren();
  if (pgStarted) {
    spawnSync("pg_ctl", ["-D", pgData, "stop"], { encoding: "utf8", stdio: "ignore" });
    pgStarted = false;
  }
  if (!keepTmp) {
    await rm(tmpRoot, { recursive: true, force: true });
  }
}

async function waitFor(label, fn, attempts = 120) {
  let lastError;
  for (let index = 0; index < attempts; index += 1) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  throw new Error(`${label} did not become ready: ${lastError?.message ?? lastError}`);
}

async function http(pathOrUrl, init = {}, expected = 200) {
  const url = pathOrUrl.startsWith("http") ? pathOrUrl : `${apiBaseForPath(pathOrUrl)}${pathOrUrl}`;
  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {})
    }
  });
  const text = await response.text();
  let body = text;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    // HTML is expected for the frontend root.
  }
  if (response.status !== expected) {
    throw new Error(`${init.method ?? "GET"} ${url} expected ${expected}, got ${response.status}: ${text.slice(0, 1000)}`);
  }
  return body;
}

function apiBaseForPath(value) {
  if (/^\/api\/(auth|me|users|permissions|models|system)(?:\/|$)/.test(value)) return `http://127.0.0.1:${commonPort}`;
  if (/^\/internal\/(auth|models)(?:\/|$)/.test(value)) return `http://127.0.0.1:${commonPort}`;
  if (
    value === "/api/projects" ||
    value === "/api/projects/discover" ||
    value === "/api/projects/join-by-invite" ||
    /^\/api\/projects\/[^/]+$/.test(value) ||
    /^\/api\/projects\/[^/]+\/(members|settings|effective-config|join-requests|invitations|audit-logs)(?:\/|$)/.test(value)
  ) {
    return `http://127.0.0.1:${commonPort}`;
  }
  return `http://127.0.0.1:${mrPort}`;
}

async function pgClient(database = dbName) {
  const client = new Client({ connectionString: `postgresql://neochen@127.0.0.1:${pgPort}/${database}` });
  await client.connect();
  return client;
}

function writeConfig(file, pythonBin = "") {
  writeFileSync(file, `${JSON.stringify({
    llm: {
      default_provider: "dashscope-openai-compatible",
      default_base_url: "https://ark.cn-beijing.volces.com/api/coding/v3",
      default_model: "MiniMax-M2.7",
      default_api_key: "test-api-key",
      default_api_key_env: "MINIMAX_API_KEY",
      request_timeout_seconds: 30,
      max_output_tokens: 4096,
      enable_stream: false
    },
    github: {
      default_token_env: "GITHUB_TOKEN",
      default_endpoint: "https://api.github.com"
    },
    codehub: {
      default_token_env: "CODEHUB_TOKEN",
      default_endpoint: ""
    },
    server: {
      host: "127.0.0.1",
      port: mrPort,
      common_port: commonPort,
      mr_port: mrPort,
      database_driver: "postgres",
      postgres_url: pgUrl,
      postgres_user: "",
      postgres_password: "",
      postgres_query_timeout_seconds: 120
    },
    logging: {
      enabled: false,
      dir: path.join(tmpRoot, "logs"),
      api_file: "jolt-api.log",
      worker_file: "jolt-worker.log",
      review_run_dir: "review-runs"
    },
    runtime: pythonBin ? { python_bin: pythonBin } : {}
  }, null, 2)}\n`, "utf8");
}

function fixtureFile(filename, lines) {
  return {
    filename,
    status: "modified",
    additions: lines.length,
    deletions: 0,
    changes: lines.length,
    patch: `@@ -0,0 +1,${lines.length} @@\n${lines.map((line) => `+${line}`).join("\n")}\n`
  };
}

async function seedReviewFixture(mrRepoDir) {
  const fixtureDir = path.join(mrRepoDir, "data", "fixtures");
  mkdirSync(fixtureDir, { recursive: true });
  const fixturePath = path.join(fixtureDir, "split-full-regression-files.json");
  const fixtureRows = [
    fixtureFile("src/main/java/com/acme/payment/PaymentQueryService.java", [
      "package com.acme.payment;",
      "import java.sql.Connection;",
      "import java.sql.ResultSet;",
      "import java.sql.Statement;",
      "import javax.sql.DataSource;",
      "public class PaymentQueryService {",
      "  private final DataSource dataSource;",
      "  public PaymentQueryService(DataSource dataSource) { this.dataSource = dataSource; }",
      "  public String find(String userId) throws Exception {",
      "    String sql = \"select * from payments where user_id='\" + userId + \"'\";",
      "    try (Connection c = dataSource.getConnection(); Statement s = c.createStatement(); ResultSet rs = s.executeQuery(sql)) {",
      "      return rs.next() ? rs.getString(\"id\") : \"\";",
      "    }",
      "  }",
      "}"
    ]),
    fixtureFile("src/main/resources/application-prod.yml", [
      "spring:",
      "  datasource:",
      "    url: jdbc:mysql://mysql.internal/payment",
      "    username: payment_app",
      "    password: paymentRoot123"
    ])
  ];
  writeFileSync(fixturePath, JSON.stringify(fixtureRows, null, 2), "utf8");

  const repoId = "repo_split_full_regression";
  const mrId = "mr_split_full_regression_9901";
  const jobId = `job_${randomUUID().replace(/-/g, "").slice(0, 16)}`;
  const headSha = `split_full_${Date.now()}`;
  const client = await pgClient();
  try {
    await client.query(`
      INSERT INTO repositories (id, project_id, provider, external_repo_id, name, default_branch, status, provider_config_json)
      VALUES ($1, 'project_default', 'github', 'jolt-fixture/split-full-regression', 'split-full-regression', 'main', 'active', $2)
      ON CONFLICT(project_id, provider, external_repo_id) DO UPDATE SET
        provider_config_json = EXCLUDED.provider_config_json,
        status = 'active',
        updated_at = CURRENT_TIMESTAMP
    `, [repoId, JSON.stringify({
      endpoint: "https://api.github.com",
      owner: "jolt-fixture",
      repo: "split-full-regression",
      fixture_changed_files: path.relative(mrRepoDir, fixturePath)
    })]);
    await client.query(`
      INSERT INTO merge_requests (
        id, repository_id, external_mr_id, number, title, author, source_branch, target_branch,
        review_status, risk_score, latest_head_sha, html_url, metadata_json, updated_at
      )
      VALUES ($1, $2, '9901', 9901, 'Split full regression fixture', 'fixture-user', 'feature/split-full', 'main',
        'queued', 98, $3, 'https://github.com/jolt-fixture/split-full-regression/pull/9901', $4, CURRENT_TIMESTAMP)
      ON CONFLICT(repository_id, external_mr_id) DO UPDATE SET
        review_status = 'queued',
        latest_head_sha = EXCLUDED.latest_head_sha,
        metadata_json = EXCLUDED.metadata_json,
        updated_at = CURRENT_TIMESTAMP
    `, [mrId, repoId, headSha, JSON.stringify({ fixture: true, additions: 20, changed_files: fixtureRows.length })]);
    await client.query("UPDATE review_jobs SET status = 'superseded', updated_at = CURRENT_TIMESTAMP WHERE merge_request_id = $1 AND status = 'queued'", [mrId]);
    await client.query(`
      INSERT INTO review_jobs (id, merge_request_id, head_sha, status, priority, requested_effort_level, requested_by)
      VALUES ($1, $2, $3, 'queued', 999, 'fast', 'user_local_admin')
    `, [jobId, mrId, headSha]);
  } finally {
    await client.end();
  }
  return { repoId, mrId, jobId, headSha, fixturePath };
}

async function queryOne(sql, params = []) {
  const client = await pgClient();
  try {
    const result = await client.query(sql, params);
    return result.rows[0];
  } finally {
    await client.end();
  }
}

async function queryAll(sql, params = []) {
  const client = await pgClient();
  try {
    const result = await client.query(sql, params);
    return result.rows;
  } finally {
    await client.end();
  }
}

async function main() {
  console.log(`Temporary regression root: ${tmpRoot}`);
  run("initdb", ["-D", pgData, "--auth=trust", "--username=neochen"]);
  run("pg_ctl", ["-D", pgData, "-o", `-h 127.0.0.1 -k ${tmpRoot} -p ${pgPort}`, "-l", path.join(tmpRoot, "postgres.log"), "start"]);
  pgStarted = true;
  await waitFor("PostgreSQL", async () => {
    run("pg_isready", ["-h", "127.0.0.1", "-p", String(pgPort), "-U", "neochen"]);
  });
  const admin = await pgClient("postgres");
  try {
    await admin.query(`CREATE DATABASE ${dbName}`);
  } finally {
    await admin.end();
  }

  run("node", ["scripts/export-three-repos.mjs", "--force", `--out=${splitRoot}`]);
  const commonDir = path.join(splitRoot, "common-backend");
  const mrDir = path.join(splitRoot, "mr-backend");
  const frontendDir = path.join(splitRoot, "frontend");

  if (!skipInstall) {
    for (const dir of [commonDir, mrDir, frontendDir]) {
      run(npmCommand, ["install", "--no-audit", "--no-fund", "--prefer-offline"], { cwd: dir, stdio: "inherit" });
    }
  }
  for (const dir of [commonDir, mrDir, frontendDir]) {
    run(npmCommand, ["run", "build"], { cwd: dir, stdio: "inherit" });
  }

  const venvPython = path.join(mrDir, ".venv", "bin", "python");
  if (!existsSync(venvPython)) {
    run("python3", ["-m", "venv", ".venv"], { cwd: mrDir, stdio: "inherit" });
  }
  run(venvPython, ["-m", "pip", "install", "-r", "requirements.txt"], { cwd: mrDir, stdio: "inherit" });

  const configPath = path.join(tmpRoot, "config.json");
  writeConfig(configPath, venvPython);
  const serviceEnv = {
    CONFIG_PATH: configPath,
    JOLT_INTERNAL_SERVICE_TOKEN: internalToken,
    PYTHON_BIN: venvPython
  };

  start("common-backend", "node", ["build/backend/common-server.js"], { cwd: commonDir, env: serviceEnv });
  await waitFor("common backend", () => http(`http://127.0.0.1:${commonPort}/api/health`));
  start("mr-backend", "node", ["build/backend/mr-server.js"], { cwd: mrDir, env: serviceEnv });
  await waitFor("MR backend", () => http(`http://127.0.0.1:${mrPort}/api/health`));
  start("frontend", npmCommand, ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(frontendPort), "--strictPort"], {
    cwd: frontendDir,
    env: {
      VITE_COMMON_API_BASE: `http://127.0.0.1:${commonPort}`,
      VITE_MR_API_BASE: `http://127.0.0.1:${mrPort}`,
      VITE_API_BASE: `http://127.0.0.1:${mrPort}`
    }
  });
  await waitFor("frontend", () => http(`http://127.0.0.1:${frontendPort}/`));

  const commonHealth = await http(`http://127.0.0.1:${commonPort}/api/health`);
  const mrHealth = await http(`http://127.0.0.1:${mrPort}/api/health`);
  if (commonHealth.service !== "jolt-common-backend") throw new Error(`common service mismatch: ${JSON.stringify(commonHealth)}`);
  if (mrHealth.service !== "jolt-mr-backend") throw new Error(`MR service mismatch: ${JSON.stringify(mrHealth)}`);

  await http(`http://127.0.0.1:${commonPort}/api/mr-review/projects/project_default/merge-requests`, {}, 404);
  await http(`http://127.0.0.1:${mrPort}/api/auth/session`, {}, 404);
  await http("/internal/models/effective-config?project_id=project_default", {}, 401);
  const internalModel = await http("/internal/models/effective-config?project_id=project_default", {
    headers: { "x-internal-service-token": internalToken }
  });
  if ("default_api_key" in (internalModel.llm ?? {})) throw new Error("internal model config leaked default_api_key");

  const login = await http("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username: "local-admin", password: "admin123" })
  });
  const auth = { Authorization: `Bearer ${login.token}` };
  await http("/api/auth/session", { headers: auth });
  await http("/api/me", { headers: auth });
  await http("/api/me/profile", {
    method: "PATCH",
    headers: auth,
    body: JSON.stringify({ display_name: "Split Regression Admin", email: "local@example.com" })
  });
  await http("/api/me/settings/preferences", {
    method: "PATCH",
    headers: auth,
    body: JSON.stringify({ value: { density: "compact", regression: true } })
  });
  await http("/api/permissions/roles", { headers: auth });
  await http("/api/permissions/me", { headers: auth });
  await http("/api/models/effective-config?project_id=project_default", { headers: auth });
  await http("/api/models/projects/project_default", {
    method: "PATCH",
    headers: auth,
    body: JSON.stringify({
      default_provider: "dashscope-openai-compatible",
      default_base_url: "https://ark.cn-beijing.volces.com/api/coding/v3",
      default_model: "MiniMax-M2.7",
      default_api_key_env: "MINIMAX_API_KEY",
      request_timeout_seconds: 30,
      max_output_tokens: 4096,
      enable_stream: false
    })
  });
  await http("/api/system/storage", { headers: auth });
  const storageTest = await http("/api/system/storage/test", {
    method: "POST",
    headers: auth,
    body: JSON.stringify({ postgres_url: pgUrl })
  });
  if (!storageTest.ok) throw new Error(`storage test failed: ${JSON.stringify(storageTest)}`);

  const projectCreate = await http("/api/projects", {
    method: "POST",
    headers: auth,
    body: JSON.stringify({
      name: "Split Regression Project",
      description: "created by split full regression",
      repository: {
        provider: "github",
        git_url: "https://github.com/jolt-fixture/split-regression-api.git",
        name: "split-regression-api"
      }
    })
  });
  const projectId = projectCreate.project.id;
  const project = await http(`/api/projects/${projectId}`, { headers: auth });
  if (project.id !== projectId) throw new Error(`project read mismatch: ${JSON.stringify(project)}`);
  await http(`/api/projects/${projectId}`, {
    method: "PATCH",
    headers: auth,
    body: JSON.stringify({ description: "updated by regression", data_policy: { mode: "split-regression" } })
  });
  const member = await http(`/api/projects/${projectId}/members`, {
    method: "POST",
    headers: auth,
    body: JSON.stringify({ username: "split-reviewer", display_name: "Split Reviewer", role: "reviewer" })
  });
  await http(`/api/projects/${projectId}/members/${member.id}`, {
    method: "PATCH",
    headers: auth,
    body: JSON.stringify({ role: "developer" })
  });
  await http(`/api/permissions/projects/${projectId}/members`, { headers: auth });
  await http(`/api/permissions/projects/${projectId}/members/${member.id}`, {
    method: "PATCH",
    headers: auth,
    body: JSON.stringify({ role: "reviewer" })
  });

  const repo = await http(`/api/projects/${projectId}/repositories`, {
    method: "POST",
    headers: auth,
    body: JSON.stringify({ git_url: "https://github.com/jolt-fixture/split-regression-service.git", provider: "github" })
  });
  await http(`/api/projects/${projectId}/repositories`, { headers: auth });
  await http(`/api/projects/${projectId}/settings`, { headers: auth });
  await http(`http://127.0.0.1:${mrPort}/api/projects/${projectId}/settings`, { headers: auth }, 404);
  await http(`/api/projects/${projectId}/effective-config`, { headers: auth });
  await http(`/api/projects/${projectId}/agents`, { headers: auth });
  await http(`/api/projects/${projectId}/expert-profiles`, { headers: auth });
  await http(`/api/projects/${projectId}/rule-sets`, { headers: auth });
  await http(`/api/projects/${projectId}/rule-documents`, { headers: auth });
  await http(`/api/projects/${projectId}/custom-skills`, { headers: auth });
  await http(`/api/projects/${projectId}/review-policy`, { headers: auth });
  await http(`/api/projects/${projectId}/queue/summary`, { headers: auth });
  await http(`/api/projects/${projectId}/toolchain/status`, { headers: auth });
  await http(`/api/projects/${projectId}/static-tools/availability`, { headers: auth });
  await http(`/api/projects/${projectId}/agents/quality`, { headers: auth });
  await http(`/api/projects/${projectId}/review-quality/summary`, { headers: auth });
  await http(`/api/projects/${projectId}/evaluation-reports`, { headers: auth });
  await http(`/api/projects/${projectId}/rule-health`, { headers: auth });
  await http(`/api/observability/review-quality?project_id=${projectId}`, { headers: auth });
  await http(`/api/vcs/${projectId}/capabilities`, { headers: auth });
  const fullJob = await http(`/api/full-review/projects/${projectId}/jobs`, {
    method: "POST",
    headers: auth,
    body: JSON.stringify({ repository_id: repo.id, commit_sha: "split-regression-head", scope: { mode: "repository" } })
  });
  await http(`/api/full-review/jobs/${fullJob.id}`, { headers: auth });
  await http(`/api/full-review/jobs/${fullJob.id}/cancel`, { method: "POST", headers: auth, body: "{}" });

  const fixture = await seedReviewFixture(mrDir);
  run(npmCommand, ["run", "worker:once"], { cwd: mrDir, env: serviceEnv, stdio: "inherit" });
  const job = await queryOne("SELECT status, attempt FROM review_jobs WHERE id = $1", [fixture.jobId]);
  if (!job || ["failed", "dead_letter"].includes(job.status)) {
    throw new Error(`review worker failed for fixture job: ${JSON.stringify(job)}`);
  }
  const runs = await queryAll(`
    SELECT rr.* FROM review_runs rr
    JOIN review_jobs rj ON rj.id = rr.review_job_id
    WHERE rj.id = $1
    ORDER BY rr.started_at DESC
  `, [fixture.jobId]);
  if (!runs.length) throw new Error("fixture review job produced no review run");
  if (["failed", "dead_letter"].includes(String(runs[0].status))) {
    throw new Error(`fixture review run failed: ${JSON.stringify(runs[0])}`);
  }
  const findings = await queryAll("SELECT id, title, severity FROM review_findings WHERE review_run_id = $1 ORDER BY created_at", [runs[0].id]);
  const mrDetail = await http(`/api/mr-review/merge-requests/${fixture.mrId}`, { headers: auth });
  if (!mrDetail.runs?.length) throw new Error("MR detail did not include review runs");
  await http(`/api/mr-review/merge-requests/${fixture.mrId}/logs`, { headers: auth });
  await http(`/api/mr-review/review-runs/${runs[0].id}`, { headers: auth });
  await http(`/api/mr-review/review-runs/${runs[0].id}/trace`, { headers: auth });
  await http(`/api/mr-review/review-runs/${runs[0].id}/session-logs`, { headers: auth });
  await http(`/api/mr-review/review-runs/${runs[0].id}/artifacts`, { headers: auth });
  await http(`/api/mr-review/projects/project_default/merge-requests`, { headers: auth });
  await http(`/api/mr-review/projects/project_default/dead-letters`, { headers: auth });
  await http(`/api/projects/${projectId}/repositories/${repo.id}`, { method: "DELETE", headers: auth });

  const tableCount = await queryOne("SELECT COUNT(*)::int AS count FROM information_schema.tables WHERE table_schema = 'public'");
  const counts = await queryOne(`
    SELECT
      (SELECT COUNT(*)::int FROM users) AS users,
      (SELECT COUNT(*)::int FROM projects) AS projects,
      (SELECT COUNT(*)::int FROM repositories) AS repositories,
      (SELECT COUNT(*)::int FROM merge_requests) AS merge_requests,
      (SELECT COUNT(*)::int FROM review_jobs) AS review_jobs,
      (SELECT COUNT(*)::int FROM review_runs) AS review_runs
  `);

  const result = {
    ok: true,
    tmpRoot,
    ports: { pg: pgPort, common: commonPort, mr: mrPort, frontend: frontendPort },
    services: { common: commonHealth.service, mr: mrHealth.service },
    project: { id: projectId, repository_id: repo.id, full_review_job_id: fullJob.id },
    fixture: {
      mr_id: fixture.mrId,
      job_id: fixture.jobId,
      job_status: job.status,
      run_id: runs[0].id,
      run_status: runs[0].status,
      finding_count: findings.length
    },
    postgres: {
      table_count: tableCount.count,
      counts
    }
  };
  console.log(JSON.stringify(result, null, 2));
}

try {
  await main();
  await cleanup();
} catch (error) {
  console.error(error instanceof Error ? error.stack : error);
  for (const item of children) {
    console.error(`\n--- ${item.label} output ---\n${item.output.join("")}`);
  }
  console.error(`Temporary files kept at ${tmpRoot}`);
  process.exitCode = 1;
  await stopChildren();
  if (pgStarted && !keepTmp) {
    spawnSync("pg_ctl", ["-D", pgData, "stop"], { encoding: "utf8", stdio: "ignore" });
  }
}
