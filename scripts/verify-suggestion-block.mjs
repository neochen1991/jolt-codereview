import { DatabaseSync } from "node:sqlite";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { loadConfig, root } from "./config-utils.mjs";

const API = process.env.API_BASE || "http://127.0.0.1:8011";
const PROJECT_ID = process.env.PROJECT_ID || "project_default";

function id(prefix) {
  return `${prefix}_${randomUUID().replace(/-/g, "").slice(0, 16)}`;
}

function dbPath() {
  const config = loadConfig();
  return path.resolve(root, config.server?.database_path || "data/jolt-codereview.sqlite");
}

async function request(pathname, init) {
  const response = await fetch(`${API}${pathname}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    }
  });
  const text = await response.text();
  const json = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(`${pathname} failed: ${response.status} ${text}`);
  }
  return json;
}

function ensureSuggestionFinding() {
  const db = new DatabaseSync(dbPath());
  const row = db.prepare(`
    SELECT rf.id, r.project_id, mr.id AS mr_id
    FROM review_findings rf
    JOIN review_runs rr ON rr.id = rf.review_run_id
    JOIN review_jobs rj ON rj.id = rr.review_job_id
    JOIN merge_requests mr ON mr.id = rj.merge_request_id
    JOIN repositories r ON r.id = mr.repository_id
    WHERE rf.selected = 1
      AND rf.line_start IS NOT NULL
      AND COALESCE(rf.line_end, rf.line_start) - rf.line_start + 1 <= 30
      AND length(trim(rf.suggested_code)) > 0
    ORDER BY rf.created_at DESC
    LIMIT 1
  `).get();
  db.close();
  if (!row) {
    throw new Error("No selected finding with suggested_code and <=30 line span was found");
  }
  return row;
}

function seedSuggestionPublishFixture() {
  const db = new DatabaseSync(dbPath());
  const repoId = "repo_github_suggestion_fixture";
  const mrId = `mr_${repoId}_9201`;
  const jobId = id("job");
  const runId = id("run");
  const findingId = id("finding");
  const headSha = `suggestion_fixture_${Date.now()}`;
  const providerConfig = {
    endpoint: "https://api.github.com",
    owner: "jolt-fixture",
    repo: "suggestion-service",
    token_env: "GITHUB_TOKEN",
    git_url: "https://github.com/jolt-fixture/suggestion-service.git"
  };

  db.prepare(`
    INSERT INTO repositories (id, project_id, provider, external_repo_id, name, default_branch, status, provider_config_json)
    VALUES (?, ?, 'github', 'jolt-fixture/suggestion-service', 'suggestion-service', 'main', 'active', ?)
    ON CONFLICT(project_id, provider, external_repo_id) DO UPDATE SET
      provider_config_json = excluded.provider_config_json,
      status = 'active',
      updated_at = CURRENT_TIMESTAMP
  `).run(repoId, PROJECT_ID, JSON.stringify(providerConfig));

  db.prepare(`
    INSERT INTO merge_requests (
      id, repository_id, external_mr_id, number, title, author, source_branch, target_branch,
      review_status, risk_score, latest_head_sha, html_url, metadata_json, updated_at
    )
    VALUES (?, ?, '9201', 9201, 'Suggestion block publish fixture', 'fixture-user', 'feature/suggestion', 'main',
      'waiting_confirmation', 80, ?, 'https://github.com/jolt-fixture/suggestion-service/pull/9201', ?, CURRENT_TIMESTAMP)
    ON CONFLICT(repository_id, external_mr_id) DO UPDATE SET
      review_status = 'waiting_confirmation',
      latest_head_sha = excluded.latest_head_sha,
      metadata_json = excluded.metadata_json,
      updated_at = CURRENT_TIMESTAMP
  `).run(mrId, repoId, headSha, JSON.stringify({ provider: "github", fixture: true, purpose: "suggestion_block" }));

  db.prepare(`
    INSERT INTO review_jobs (id, merge_request_id, head_sha, status, priority, requested_effort_level)
    VALUES (?, ?, ?, 'waiting_confirmation', 1000, 'standard')
  `).run(jobId, mrId, headSha);

  db.prepare(`
    INSERT INTO review_runs (
      id, review_job_id, effort_level, risk_score, budget_json, budget_used_json,
      coverage_json, toolchain_manifest, data_policy_snapshot, status, report_summary, completed_at
    )
    VALUES (?, ?, 'standard', 80, '{}', '{}', '{}', '{}', '{}', 'waiting_confirmation', 'suggestion fixture', CURRENT_TIMESTAMP)
  `).run(runId, jobId);

  db.prepare(`
    INSERT INTO review_findings (
      id, review_run_id, severity, confidence, agent_id, head_sha, dedupe_hash,
      file_path, line_start, line_end, title, problem_description, recommendation,
      suggested_code, evidence, covered_rules_json, selected
    )
    VALUES (?, ?, 'high', 0.92, 'security_agent', ?, ?, 'src/main/java/com/acme/UserController.java',
      42, 42, '缺少权限校验', '用户更新接口没有校验当前操作者是否具备 admin 权限。',
      '在更新前校验当前用户权限。',
      'if (!currentUser.hasRole(\"admin\")) {\n    throw new AccessDeniedException(\"admin role required\");\n}',
      'updateUser(request);', '[\"BACKEND-AUTH-001\"]', 1)
  `).run(findingId, runId, headSha, `suggestion-${headSha}`);
  db.close();
  return { mr_id: mrId, id: findingId };
}

let finding;
try {
  finding = ensureSuggestionFinding();
} catch {
  finding = seedSuggestionPublishFixture();
}

const publish = await request(`/api/mr-review/merge-requests/${finding.mr_id}/publish`, {
  method: "POST",
  body: JSON.stringify({ finding_ids: [finding.id], dry_run: true })
});

if (!publish.body.includes("```suggestion\n")) {
  throw new Error("dry-run publish body did not include a GitHub suggestion block");
}
if (!publish.body.includes("关联 head_sha:")) {
  throw new Error("publish body lost existing head_sha footer");
}

console.log(JSON.stringify({
  ok: true,
  mr_id: finding.mr_id,
  finding_id: finding.id,
  published_count: publish.published_count,
  has_suggestion_block: true
}, null, 2));
