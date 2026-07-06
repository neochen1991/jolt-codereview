import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { Client } from "pg";

const root = path.resolve(import.meta.dirname, "..");
const manifestDir = path.join(root, "evaluation", "real_prs");
const cacheDir = path.join(manifestDir, "cache");

function parseArgs(argv) {
  const args = {
    manifestDir,
    cacheDir,
    projectId: process.env.PROJECT_ID || "project_default",
    configPath: process.env.CONFIG_PATH || process.env.MR_CONFIG_PATH || path.join(root, "mr-backend", "config.json"),
    writeDb: false,
    offline: false
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--write-db") args.writeDb = true;
    else if (arg === "--offline") args.offline = true;
    else if (arg === "--manifest-dir") args.manifestDir = path.resolve(argv[++i]);
    else if (arg === "--cache-dir") args.cacheDir = path.resolve(argv[++i]);
    else if (arg === "--project-id") args.projectId = argv[++i];
    else if (arg === "--config") args.configPath = path.resolve(argv[++i]);
    else throw new Error(`Unknown argument: ${arg}`);
  }
  return args;
}

function readJson(file) {
  return JSON.parse(readFileSync(file, "utf8"));
}

function listManifestFiles(dir) {
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((name) => name.endsWith(".json"))
    .filter((name) => !["latest-export-report.json"].includes(name))
    .map((name) => path.join(dir, name));
}

function requireField(value, name) {
  if (value === undefined || value === null || value === "") throw new Error(`Missing required manifest field: ${name}`);
  return value;
}

function normalizeManifest(raw, sourcePath) {
  const repository = raw.repository || {};
  const owner = String(requireField(repository.owner ?? raw.owner, "repository.owner"));
  const repo = String(requireField(repository.repo ?? raw.repo, "repository.repo"));
  const pullNumber = Number(requireField(raw.pull_number ?? raw.number, "pull_number"));
  if (!Number.isInteger(pullNumber) || pullNumber <= 0) throw new Error(`Invalid pull_number in ${sourcePath}`);
  const id = String(raw.id || `${owner}-${repo}-${pullNumber}`).replace(/[^a-zA-Z0-9_-]+/g, "-").toLowerCase();
  return {
    id,
    sourcePath,
    projectId: String(raw.project_id || ""),
    repository: {
      owner,
      repo,
      endpoint: String(repository.endpoint || raw.endpoint || "https://api.github.com").replace(/\/$/, ""),
      default_branch: String(repository.default_branch || raw.default_branch || "main"),
      git_url: String(repository.git_url || `https://github.com/${owner}/${repo}.git`)
    },
    pull_number: pullNumber,
    expected_gold_ids: Array.isArray(raw.expected_gold_ids) ? raw.expected_gold_ids.map(String) : [],
    tags: Array.isArray(raw.tags) ? raw.tags.map(String) : []
  };
}

function headers() {
  const token = process.env.GITHUB_TOKEN || "";
  return {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "jolt-codereview-real-pr-seeder",
    ...(token ? { "Authorization": `Bearer ${token}` } : {})
  };
}

async function fetchJson(url) {
  const response = await fetch(url, { headers: headers() });
  if (!response.ok) throw new Error(`GET ${url} failed: ${response.status} ${await response.text()}`);
  return await response.json();
}

async function fetchText(url, accept) {
  const response = await fetch(url, { headers: { ...headers(), Accept: accept } });
  if (!response.ok) throw new Error(`GET ${url} failed: ${response.status} ${await response.text()}`);
  return await response.text();
}

function cachePaths(cacheRoot, manifest) {
  const dir = path.join(cacheRoot, manifest.id);
  return {
    dir,
    pull: path.join(dir, "pull.json"),
    files: path.join(dir, "files.json"),
    diff: path.join(dir, "pull.diff")
  };
}

async function loadOrFetchFixture(manifest, cacheRoot, offline) {
  const paths = cachePaths(cacheRoot, manifest);
  mkdirSync(paths.dir, { recursive: true });
  if (offline) {
    if (!existsSync(paths.pull) || !existsSync(paths.files) || !existsSync(paths.diff)) {
      throw new Error(`Offline cache missing for ${manifest.id}; run without --offline first.`);
    }
    return {
      pull: readJson(paths.pull),
      files: readJson(paths.files),
      diff: readFileSync(paths.diff, "utf8"),
      cached: true
    };
  }
  const base = `${manifest.repository.endpoint}/repos/${encodeURIComponent(manifest.repository.owner)}/${encodeURIComponent(manifest.repository.repo)}/pulls/${manifest.pull_number}`;
  const [pull, files, diff] = await Promise.all([
    fetchJson(base),
    fetchJson(`${base}/files?per_page=100`),
    fetchText(base, "application/vnd.github.v3.diff")
  ]);
  writeFileSync(paths.pull, JSON.stringify(pull, null, 2));
  writeFileSync(paths.files, JSON.stringify(files, null, 2));
  writeFileSync(paths.diff, diff);
  return { pull, files, diff, cached: false };
}

function loadConfig(configPath) {
  if (!existsSync(configPath)) return {};
  return readJson(configPath);
}

function postgresConfig(config) {
  const server = config.server || {};
  const connectionString = process.env.POSTGRES_URL || process.env.DATABASE_URL || server.postgres_url || "";
  if (connectionString) return { connectionString };
  return {
    host: server.postgres_host || "127.0.0.1",
    port: Number(server.postgres_port || 5432),
    database: server.postgres_database || server.postgres_db || "jolt_codereview",
    user: process.env.POSTGRES_USER || server.postgres_user || "",
    password: process.env.POSTGRES_PASSWORD || server.postgres_password || ""
  };
}

function repoId(projectId, manifest) {
  return `repo_real_${projectId}_${manifest.repository.owner}_${manifest.repository.repo}`.replace(/[^a-zA-Z0-9_-]+/g, "_").toLowerCase();
}

function mrId(projectId, manifest) {
  return `mr_real_${projectId}_${manifest.repository.owner}_${manifest.repository.repo}_${manifest.pull_number}`.replace(/[^a-zA-Z0-9_-]+/g, "_").toLowerCase();
}

function jobId(projectId, manifest, headSha) {
  return `job_real_${projectId}_${manifest.repository.owner}_${manifest.repository.repo}_${manifest.pull_number}_${String(headSha).slice(0, 12)}`.replace(/[^a-zA-Z0-9_-]+/g, "_").toLowerCase();
}

function riskScore(files) {
  const additions = files.reduce((sum, file) => sum + Number(file.additions || 0), 0);
  const deletions = files.reduce((sum, file) => sum + Number(file.deletions || 0), 0);
  const fileCount = files.length;
  return Math.min(100, Math.round(fileCount * 3 + additions / 25 + deletions / 50));
}

async function writeFixture(client, projectId, manifest, fixture, cacheRoot) {
  const repositoryId = repoId(projectId, manifest);
  const mergeRequestId = mrId(projectId, manifest);
  const headSha = String(fixture.pull.head?.sha || fixture.pull.head?.ref || `pr-${manifest.pull_number}`);
  const reviewJobId = jobId(projectId, manifest, headSha);
  await client.query("BEGIN");
  try {
    await client.query(
      `INSERT INTO repositories (id, project_id, provider, external_repo_id, name, default_branch, status, provider_config_json)
       VALUES ($1, $2, 'github', $3, $4, $5, 'active', $6)
       ON CONFLICT(project_id, provider, external_repo_id) DO UPDATE SET
         name = EXCLUDED.name,
         default_branch = EXCLUDED.default_branch,
         status = 'active',
         provider_config_json = EXCLUDED.provider_config_json,
         updated_at = CURRENT_TIMESTAMP`,
      [
        repositoryId,
        projectId,
        `${manifest.repository.owner}/${manifest.repository.repo}`,
        manifest.repository.repo,
        String(fixture.pull.base?.ref || manifest.repository.default_branch),
        JSON.stringify({
          owner: manifest.repository.owner,
          repo: manifest.repository.repo,
          endpoint: manifest.repository.endpoint,
          git_url: manifest.repository.git_url,
          real_pr_fixture_id: manifest.id
        })
      ]
    );
    await client.query(
      `INSERT INTO merge_requests (
         id, repository_id, external_mr_id, number, title, author, source_branch, target_branch,
         review_status, risk_score, latest_head_sha, html_url, metadata_json, updated_at
       )
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'queued', $9, $10, $11, $12, CURRENT_TIMESTAMP)
       ON CONFLICT(repository_id, external_mr_id) DO UPDATE SET
         title = EXCLUDED.title,
         author = EXCLUDED.author,
         source_branch = EXCLUDED.source_branch,
         target_branch = EXCLUDED.target_branch,
         risk_score = EXCLUDED.risk_score,
         latest_head_sha = EXCLUDED.latest_head_sha,
         html_url = EXCLUDED.html_url,
         metadata_json = EXCLUDED.metadata_json,
         review_status = CASE WHEN merge_requests.latest_head_sha != EXCLUDED.latest_head_sha THEN 'queued' ELSE merge_requests.review_status END,
         updated_at = CURRENT_TIMESTAMP`,
      [
        mergeRequestId,
        repositoryId,
        String(fixture.pull.id || manifest.pull_number),
        manifest.pull_number,
        String(fixture.pull.title || `PR #${manifest.pull_number}`),
        String(fixture.pull.user?.login || "unknown"),
        String(fixture.pull.head?.ref || ""),
        String(fixture.pull.base?.ref || manifest.repository.default_branch),
        riskScore(fixture.files),
        headSha,
        String(fixture.pull.html_url || `https://github.com/${manifest.repository.owner}/${manifest.repository.repo}/pull/${manifest.pull_number}`),
        JSON.stringify({
          real_pr_fixture_id: manifest.id,
          expected_gold_ids: manifest.expected_gold_ids,
          tags: manifest.tags,
          changed_files: fixture.files.length,
          additions: fixture.files.reduce((sum, file) => sum + Number(file.additions || 0), 0),
          deletions: fixture.files.reduce((sum, file) => sum + Number(file.deletions || 0), 0)
        })
      ]
    );
    await client.query(
      `INSERT INTO review_jobs (id, merge_request_id, head_sha, status, priority, requested_effort_level, requested_by, pr_summary)
       VALUES ($1, $2, $3, 'queued', $4, 'standard', 'real-pr-seed', $5)
       ON CONFLICT(merge_request_id, head_sha) DO UPDATE SET
         status = 'queued',
         priority = EXCLUDED.priority,
         requested_by = EXCLUDED.requested_by,
         pr_summary = EXCLUDED.pr_summary,
         attempt = 0,
         locked_at = NULL,
         locked_by = NULL,
         heartbeat_at = NULL,
         updated_at = CURRENT_TIMESTAMP`,
      [
        reviewJobId,
        mergeRequestId,
        headSha,
        riskScore(fixture.files),
        JSON.stringify({
          real_pr_fixture_id: manifest.id,
          diff_cache_path: path.relative(root, cachePaths(cacheRoot, manifest).diff),
          files_cache_path: path.relative(root, cachePaths(cacheRoot, manifest).files)
        })
      ]
    );
    await client.query("COMMIT");
    return { repository_id: repositoryId, merge_request_id: mergeRequestId, review_job_id: reviewJobId };
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const manifests = listManifestFiles(args.manifestDir).map((file) => normalizeManifest(readJson(file), file));
  if (!manifests.length) {
    throw new Error(`No real PR manifest files found in ${args.manifestDir}`);
  }
  mkdirSync(args.cacheDir, { recursive: true });
  const rows = [];
  let client = null;
  if (args.writeDb) {
    client = new Client(postgresConfig(loadConfig(args.configPath)));
    await client.connect();
  }
  try {
    for (const manifest of manifests) {
      const fixture = await loadOrFetchFixture(manifest, args.cacheDir, args.offline);
      const row = {
        id: manifest.id,
        repository: `${manifest.repository.owner}/${manifest.repository.repo}`,
        pull_number: manifest.pull_number,
        title: fixture.pull.title,
        head_sha: fixture.pull.head?.sha,
        changed_files: fixture.files.length,
        cached: fixture.cached
      };
      if (client) Object.assign(row, await writeFixture(client, manifest.projectId || args.projectId, manifest, fixture, args.cacheDir));
      rows.push(row);
    }
  } finally {
    if (client) await client.end();
  }
  console.log(JSON.stringify({ ok: true, seeded: rows.length, write_db: args.writeDb, rows }, null, 2));
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
