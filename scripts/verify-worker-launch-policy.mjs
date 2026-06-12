import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { pathToFileURL } from "node:url";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const migrationsModule = await import(pathToFileURL(path.join(root, "build/backend/db/migrations.js")));
const projectConfigModule = await import(pathToFileURL(path.join(root, "build/backend/services/ProjectConfigService.js")));
const launchModule = await import(pathToFileURL(path.join(root, "build/backend/services/WorkerLaunchPolicy.js")));

const { migrate } = migrationsModule;
const { ProjectConfigService } = projectConfigModule;
const { queuedReviewWorkerCapacity } = launchModule;

const db = new DatabaseSync(":memory:");
migrate(db);
const projectConfigService = new ProjectConfigService(db);

for (const projectId of ["project_a", "project_b", "project_c"]) {
  db.prepare("INSERT INTO projects (id, name) VALUES (?, ?)").run(projectId, projectId);
  db.prepare(`
    INSERT INTO repositories (id, project_id, provider, external_repo_id, name, default_branch, status, provider_config_json)
    VALUES (?, ?, 'github', ?, ?, 'main', 'active', '{}')
  `).run(`repo_${projectId}`, projectId, `org/${projectId}`, projectId);
  for (const index of [1, 2]) {
    db.prepare(`
      INSERT INTO merge_requests (
        id, repository_id, external_mr_id, number, title, author, source_branch, target_branch,
        review_status, risk_score, latest_head_sha, html_url, metadata_json
      )
      VALUES (?, ?, ?, ?, ?, 'tester', 'feature', 'main', 'queued', 50, ?, '', '{}')
    `).run(`mr_${projectId}_${index}`, `repo_${projectId}`, String(index), index, `MR ${index}`, `sha_${projectId}_${index}`);
    db.prepare(`
      INSERT INTO review_jobs (id, merge_request_id, head_sha, status, priority, requested_effort_level)
      VALUES (?, ?, ?, 'queued', 50, 'standard')
    `).run(`job_${projectId}_${index}`, `mr_${projectId}_${index}`, `sha_${projectId}_${index}`);
  }
}

db.prepare(`
  UPDATE review_jobs
  SET status = 'reviewing', heartbeat_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
  WHERE id = 'job_project_a_1'
`).run();

assert.equal(
  queuedReviewWorkerCapacity({ config: { queue_policy: { max_concurrency: 1 } }, db, projectConfigService }),
  2,
  "default one-per-project concurrency should still launch workers for other projects"
);

projectConfigService.upsertSetting("project_a", "queue_policy", { max_concurrency: 2 });
assert.equal(
  queuedReviewWorkerCapacity({ config: { queue_policy: { max_concurrency: 1 } }, db, projectConfigService }),
  3,
  "raising one project concurrency should add capacity for that project's queued MR"
);

db.close();
console.log("Worker launch policy checks passed.");
