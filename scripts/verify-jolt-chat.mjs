import { DatabaseSync } from "node:sqlite";
import path from "node:path";
import { loadConfig, root } from "./config-utils.mjs";

const API = process.env.API_BASE || "http://127.0.0.1:8011";
const config = loadConfig();
const db = new DatabaseSync(path.resolve(root, config.server?.database_path || "data/jolt-codereview.sqlite"));
const row = db.prepare(`
  SELECT rf.id AS finding_id, rf.file_path, rf.line_start, rj.merge_request_id
  FROM review_findings rf
  JOIN review_runs rr ON rr.id = rf.review_run_id
  JOIN review_jobs rj ON rj.id = rr.review_job_id
  WHERE rj.merge_request_id = 'mr_repo_github_java_fixture_9101'
  ORDER BY rr.started_at DESC, rf.confidence DESC
  LIMIT 1
`).get();
db.close();
if (!row) throw new Error("no finding found for jolt chat verification");

async function post(body) {
  const response = await fetch(`${API}/api/webhooks/github/project_default/jolt-comment`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  const json = await response.json();
  if (!response.ok) throw new Error(JSON.stringify(json));
  return json;
}

const explain = await post({ mr_id: row.merge_request_id, comment_body: `@jolt explain ${row.finding_id}`, dry_run: true });
if (!String(explain.body || "").includes(row.finding_id)) throw new Error("explain response does not mention finding id");

const whyNot = await post({ mr_id: row.merge_request_id, comment_body: `@jolt why-not ${row.file_path}:${row.line_start}`, dry_run: true });
if (!String(whyNot.body || "").includes("@jolt why-not")) throw new Error("why-not response missing marker");

console.log(JSON.stringify({ ok: true, explain_command: explain.command, why_not_command: whyNot.command, finding_id: row.finding_id }, null, 2));
