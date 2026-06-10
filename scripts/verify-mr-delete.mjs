import { DatabaseSync } from "node:sqlite";
import { migrate } from "../build/backend/db/migrations.js";
import { MergeRequestRepository } from "../build/backend/repositories/MergeRequestRepository.js";
import { ReviewJobRepository } from "../build/backend/repositories/ReviewJobRepository.js";
import { ReviewQueueService } from "../build/backend/services/ReviewQueueService.js";

function count(db, sql, params = []) {
  return db.prepare(sql).get(...params).count;
}

const db = new DatabaseSync(":memory:");
migrate(db);

const mergeRequestRepository = new MergeRequestRepository(db);
const reviewJobRepository = new ReviewJobRepository(db);
const reviewQueueService = new ReviewQueueService(reviewJobRepository);

db.prepare("INSERT INTO users (id, username, display_name, status) VALUES ('user_delete', 'delete-user', 'Delete User', 'active')").run();
db.prepare("INSERT INTO projects (id, name) VALUES ('project_delete', 'Delete Project')").run();
db.prepare(`
  INSERT INTO repositories (id, project_id, provider, external_repo_id, name, default_branch, status, provider_config_json)
  VALUES ('repo_delete', 'project_delete', 'codehub', 'https://codehub.example.com/team/delete-demo.git', 'delete-demo', 'main', 'active', '{}')
`).run();
mergeRequestRepository.upsert({
  id: "mr_delete_1",
  repositoryId: "repo_delete",
  externalMrId: "101",
  number: 101,
  title: "Delete fixture MR",
  author: "tester",
  sourceBranch: "feature/delete",
  targetBranch: "main",
  riskScore: 80,
  latestHeadSha: "sha-delete-1",
  htmlUrl: "https://codehub.example.com/team/delete-demo/merge_requests/101",
  metadata: { fixture: true }
});

db.prepare(`
  INSERT INTO review_jobs (id, merge_request_id, head_sha, status, priority, requested_effort_level)
  VALUES ('job_delete_1', 'mr_delete_1', 'sha-delete-1', 'queued', 80, 'standard')
`).run();
db.prepare(`
  INSERT INTO review_runs (id, review_job_id, effort_level, risk_score, status)
  VALUES ('run_delete_1', 'job_delete_1', 'standard', 80, 'completed')
`).run();
db.prepare(`
  INSERT INTO review_findings (
    id, review_run_id, severity, confidence, agent_id, head_sha, dedupe_hash,
    file_path, line_start, line_end, title, problem_description, recommendation, evidence
  )
  VALUES (
    'finding_delete_1', 'run_delete_1', 'high', 0.95, 'security_agent', 'sha-delete-1', 'hash-delete-1',
    'src/Delete.java', 10, 10, 'delete finding', 'problem', 'fix', 'evidence'
  )
`).run();
db.prepare(`
  INSERT INTO mr_finding_history (id, merge_request_id, dedupe_hash, finding_id, first_seen_head_sha, last_seen_head_sha)
  VALUES ('history_delete_1', 'mr_delete_1', 'hash-delete-1', 'finding_delete_1', 'sha-delete-1', 'sha-delete-1')
`).run();
db.prepare("INSERT INTO agent_trace_spans (id, review_run_id, span_key, status) VALUES ('span_delete_1', 'run_delete_1', 'root', 'completed')").run();
db.prepare("INSERT INTO agent_trace_events (id, span_id, event_type, summary) VALUES ('event_delete_1', 'span_delete_1', 'done', 'done')").run();
db.prepare("INSERT INTO agent_messages (id, span_id, from_agent, to_agent, role, content_summary) VALUES ('msg_delete_1', 'span_delete_1', 'a', 'b', 'assistant', 'summary')").run();
db.prepare("INSERT INTO llm_call_records (id, span_id, provider, model, status) VALUES ('llm_delete_1', 'span_delete_1', 'test', 'model', 'ok')").run();
db.prepare("INSERT INTO tool_call_records (id, span_id, tool_name, status) VALUES ('tool_call_delete_1', 'span_delete_1', 'tool', 'ok')").run();
db.prepare("INSERT INTO mcp_call_records (id, span_id, server_name, tool_name, status) VALUES ('mcp_delete_1', 'span_delete_1', 'server', 'tool', 'ok')").run();
db.prepare("INSERT INTO review_artifacts (id, review_run_id, artifact_type, name, storage_uri, sha256) VALUES ('artifact_delete_1', 'run_delete_1', 'json', 'artifact', 'memory://artifact', 'sha256')").run();
db.prepare("INSERT INTO code_index_snapshots (id, review_run_id, repository_id, commit_sha, index_kind, storage_uri) VALUES ('index_delete_1', 'run_delete_1', 'repo_delete', 'sha-delete-1', 'symbols', 'memory://index')").run();
db.prepare(`
  INSERT INTO tool_observations (id, review_run_id, tool_name, file_path, message)
  VALUES ('observation_delete_1', 'run_delete_1', 'semgrep', 'src/Delete.java', 'message')
`).run();
db.prepare(`
  INSERT INTO external_review_reports (id, merge_request_id, report_type, commit_sha, report_format)
  VALUES ('external_delete_1', 'mr_delete_1', 'sast', 'sha-delete-1', 'json')
`).run();
db.prepare(`
  INSERT INTO user_feedback (id, user_id, finding_id, dedupe_hash, feedback_type, scope)
  VALUES ('feedback_delete_1', 'user_delete', 'finding_delete_1', 'hash-delete-1', 'false_positive', 'merge_request')
`).run();
db.prepare("INSERT INTO review_jobs_dead_letter (id, review_job_id, failure_reason, final_attempt) VALUES ('dead_delete_1', 'job_delete_1', 'failed', 3)").run();
db.prepare(`
  INSERT INTO vcs_publish_records (id, finding_id, provider, publish_status, published_by, body)
  VALUES ('publish_delete_1', 'finding_delete_1', 'codehub', 'dry_run', 'user_delete', 'body')
`).run();
db.prepare(`
  INSERT INTO evaluation_gold_set (
    id, project_id, finding_id, agent_id, severity, expected_title,
    expected_file_path, expected_line, label, source
  )
  VALUES (
    'gold_delete_1', 'project_delete', 'finding_delete_1', 'security_agent', 'high', 'delete finding',
    'src/Delete.java', 10, 'true_positive', 'fixture'
  )
`).run();

const result = mergeRequestRepository.deleteById("mr_delete_1");
if (!result.ok || result.deleted_merge_requests !== 1) {
  throw new Error(`deleteById did not report one deleted MR: ${JSON.stringify(result)}`);
}
if (mergeRequestRepository.findById("mr_delete_1")) {
  throw new Error("deleted MR is still visible");
}

const counts = {
  review_jobs: count(db, "SELECT COUNT(*) AS count FROM review_jobs WHERE merge_request_id = 'mr_delete_1'"),
  review_runs: count(db, "SELECT COUNT(*) AS count FROM review_runs WHERE id = 'run_delete_1'"),
  review_findings: count(db, "SELECT COUNT(*) AS count FROM review_findings WHERE id = 'finding_delete_1'"),
  mr_finding_history: count(db, "SELECT COUNT(*) AS count FROM mr_finding_history WHERE merge_request_id = 'mr_delete_1'"),
  agent_trace_spans: count(db, "SELECT COUNT(*) AS count FROM agent_trace_spans WHERE id = 'span_delete_1'"),
  external_review_reports: count(db, "SELECT COUNT(*) AS count FROM external_review_reports WHERE merge_request_id = 'mr_delete_1'"),
  user_feedback: count(db, "SELECT COUNT(*) AS count FROM user_feedback WHERE finding_id = 'finding_delete_1'"),
  vcs_publish_records: count(db, "SELECT COUNT(*) AS count FROM vcs_publish_records WHERE finding_id = 'finding_delete_1'"),
  evaluation_gold_set: count(db, "SELECT COUNT(*) AS count FROM evaluation_gold_set WHERE finding_id = 'finding_delete_1'")
};
for (const [table, value] of Object.entries(counts)) {
  if (value !== 0) throw new Error(`${table} still has ${value} rows after MR delete`);
}

mergeRequestRepository.upsert({
  id: "mr_delete_2",
  repositoryId: "repo_delete",
  externalMrId: "101",
  number: 101,
  title: "Delete fixture MR pulled again",
  author: "tester",
  sourceBranch: "feature/delete",
  targetBranch: "main",
  riskScore: 81,
  latestHeadSha: "sha-delete-2",
  htmlUrl: "https://codehub.example.com/team/delete-demo/merge_requests/101",
  metadata: { fixture: true, repulled: true }
});
const enqueue = reviewQueueService.enqueueIdempotent({
  mergeRequestId: "mr_delete_2",
  headSha: "sha-delete-2",
  priority: 81,
  effortLevel: "standard"
});
if (!enqueue.created) throw new Error("repulled MR did not create a fresh review job");
if (!mergeRequestRepository.findByRepositoryAndExternalId("repo_delete", "101")) {
  throw new Error("repulled MR is not visible by repository/external id");
}

db.close();
console.log(JSON.stringify({ ok: true, deleted: result, repulled: "mr_delete_2" }, null, 2));
