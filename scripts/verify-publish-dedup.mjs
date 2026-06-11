import { DatabaseSync } from "node:sqlite";
import { sha1 } from "../build/backend/http.js";
import { migrate } from "../build/backend/db/migrations.js";
import { createRoutes } from "../build/backend/routes/mr-review.routes.js";

const db = new DatabaseSync(":memory:");
migrate(db);

const config = {
  github: { default_endpoint: "https://api.github.com" },
  codehub: { default_endpoint: "http://127.0.0.1:9", default_token: null },
  server: { database_driver: "sqlite" },
  logging: { enabled: false }
};

const userId = "user_publish_dedup";
const token = "publish-dedup-token";
const projectId = "project_publish_dedup";
const repoId = "repo_publish_dedup";
const mrId = "mr_publish_dedup";
const jobId = "job_publish_dedup";
const runId = "run_publish_dedup";
const alreadyPublishedFindingId = "finding_publish_dedup_done";
const pendingFindingId = "finding_publish_dedup_new";

db.prepare(`
  INSERT INTO users (id, username, display_name, global_role, status)
  VALUES (?, 'publish-dedup-user', 'Publish Dedup User', 'user', 'active')
`).run(userId);
db.prepare("INSERT INTO auth_sessions (id, user_id, token_hash, status) VALUES ('session_publish_dedup', ?, ?, 'active')")
  .run(userId, sha1(token));
db.prepare("INSERT INTO projects (id, name) VALUES (?, 'Publish Dedup Project')").run(projectId);
db.prepare("INSERT INTO project_members (id, project_id, user_id, role) VALUES ('member_publish_dedup', ?, ?, 'reviewer')")
  .run(projectId, userId);
db.prepare(`
  INSERT INTO repositories (id, project_id, provider, external_repo_id, name, default_branch, status, provider_config_json)
  VALUES (?, ?, 'codehub', 'codehub.example.com/team/service', 'service', 'main', 'active', ?)
`).run(repoId, projectId, JSON.stringify({ endpoint: "http://127.0.0.1:9", repo_id: "team/service" }));
db.prepare(`
  INSERT INTO merge_requests (
    id, repository_id, external_mr_id, number, title, author, source_branch, target_branch,
    review_status, risk_score, latest_head_sha, html_url, metadata_json
  )
  VALUES (?, ?, '101', 101, 'Publish dedup fixture', 'fixture', 'feature/dedup', 'main',
    'waiting_confirmation', 80, 'sha-publish-dedup', 'https://codehub.example.com/team/service/merge_requests/101', '{}')
`).run(mrId, repoId);
db.prepare(`
  INSERT INTO review_jobs (id, merge_request_id, head_sha, status, priority, requested_effort_level)
  VALUES (?, ?, 'sha-publish-dedup', 'waiting_confirmation', 80, 'standard')
`).run(jobId, mrId);
db.prepare(`
  INSERT INTO review_runs (id, review_job_id, effort_level, risk_score, status)
  VALUES (?, ?, 'standard', 80, 'waiting_confirmation')
`).run(runId, jobId);
db.prepare(`
  INSERT INTO review_findings (
    id, review_run_id, severity, confidence, agent_id, head_sha, dedupe_hash,
    file_path, line_start, line_end, title, problem_description, recommendation,
    evidence, publish_state, lifecycle_state, selected
  )
  VALUES (?, ?, 'high', 0.95, 'ddd_agent', 'sha-publish-dedup', 'dedup-hash-1',
    'src/domain/OrderService.java', 42, 42, '已提交问题不应重复提交',
    '这个 finding 已经提交到代码平台。', '再次点击提交时应跳过该 finding。',
    'existing published comment', 'published', 'accepted', 1)
`).run(alreadyPublishedFindingId, runId);
db.prepare(`
  INSERT INTO review_findings (
    id, review_run_id, severity, confidence, agent_id, head_sha, dedupe_hash,
    file_path, line_start, line_end, title, problem_description, recommendation,
    evidence, publish_state, lifecycle_state, selected
  )
  VALUES (?, ?, 'medium', 0.88, 'ddd_agent', 'sha-publish-dedup', 'dedup-hash-2',
    'src/domain/OrderAggregate.java', 58, 58, '新的问题可提交',
    '这个 finding 尚未提交。', '真实提交时应包含该 finding。',
    'new finding evidence', 'pending', 'pending', 1)
`).run(pendingFindingId, runId);
db.prepare(`
  INSERT INTO vcs_publish_records (
    id, finding_id, provider, external_comment_id, external_thread_id, publish_status, published_by, body
  )
  VALUES ('publish_record_done', ?, 'codehub', 'comment-1', 'comment-1', 'published', ?, 'already published body')
`).run(alreadyPublishedFindingId, userId);

const fetchCalls = [];
globalThis.fetch = async (url, init = {}) => {
  fetchCalls.push({ url: String(url), body: String(init.body || "") });
  return {
    ok: true,
    json: async () => ({ id: `comment-${fetchCalls.length}` }),
    text: async () => ""
  };
};

const routes = createRoutes(config, db);
const publishRoute = routes.find((route) => (
  route.method === "POST" &&
  route.keys.includes("mrId") &&
  route.pattern.test(`/api/mr-review/merge-requests/${mrId}/publish`)
));
if (!publishRoute) throw new Error("publish route was not registered");

const result = await publishRoute.handler({
  params: { mrId },
  body: { finding_ids: [alreadyPublishedFindingId], dry_run: false },
  req: { headers: { authorization: `Bearer ${token}` } },
  res: {},
  url: new URL(`http://localhost/api/mr-review/merge-requests/${mrId}/publish`)
});

if (result?.statusCode) {
  throw new Error(`publish route returned error: ${JSON.stringify(result)}`);
}
if (result.published_count !== 0) {
  throw new Error(`expected no duplicate publish, got ${JSON.stringify(result)}`);
}
if (result.skipped_count !== 1 || result.skipped_finding_ids?.[0] !== alreadyPublishedFindingId) {
  throw new Error(`expected one skipped already-published finding, got ${JSON.stringify(result)}`);
}
if (String(result.body || "").trim()) {
  throw new Error("duplicate-only publish should not build a platform comment body");
}
if (fetchCalls.length !== 0) {
  throw new Error(`duplicate-only publish should not call CodeHub, got ${fetchCalls.length} calls`);
}

const publishRecords = db.prepare("SELECT COUNT(*) AS count FROM vcs_publish_records WHERE finding_id = ? AND publish_status = 'published'")
  .get(alreadyPublishedFindingId).count;
if (publishRecords !== 1) {
  throw new Error(`expected exactly one published record to remain, got ${publishRecords}`);
}

const mixedResult = await publishRoute.handler({
  params: { mrId },
  body: { finding_ids: [alreadyPublishedFindingId, pendingFindingId], dry_run: false },
  req: { headers: { authorization: `Bearer ${token}` } },
  res: {},
  url: new URL(`http://localhost/api/mr-review/merge-requests/${mrId}/publish`)
});

if (mixedResult?.statusCode) {
  throw new Error(`mixed publish returned error: ${JSON.stringify(mixedResult)}`);
}
if (mixedResult.published_count !== 1 || mixedResult.skipped_count !== 1) {
  throw new Error(`expected mixed publish to publish one and skip one, got ${JSON.stringify(mixedResult)}`);
}
if (!String(mixedResult.body || "").includes("新的问题可提交")) {
  throw new Error("mixed publish body lost the new finding");
}
if (String(mixedResult.body || "").includes("已提交问题不应重复提交")) {
  throw new Error("mixed publish body included an already-published finding");
}
if (fetchCalls.length !== 1) {
  throw new Error(`mixed publish should call CodeHub once for the new finding, got ${fetchCalls.length} calls`);
}
const pendingState = db.prepare("SELECT publish_state FROM review_findings WHERE id = ?").get(pendingFindingId).publish_state;
if (pendingState !== "published") {
  throw new Error(`pending finding was not marked published: ${pendingState}`);
}
const finalPublishedRecords = db.prepare("SELECT COUNT(*) AS count FROM vcs_publish_records WHERE finding_id = ? AND publish_status = 'published'")
  .get(alreadyPublishedFindingId).count;
if (finalPublishedRecords !== 1) {
  throw new Error(`already-published finding received duplicate records: ${finalPublishedRecords}`);
}

db.close();
console.log(JSON.stringify({
  ok: true,
  duplicate_only: { published_count: result.published_count, skipped_count: result.skipped_count },
  mixed: { published_count: mixedResult.published_count, skipped_count: mixedResult.skipped_count, codehub_calls: fetchCalls.length }
}, null, 2));
