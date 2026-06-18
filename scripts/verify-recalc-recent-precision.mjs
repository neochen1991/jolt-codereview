import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { loadConfig } from "../build/backend/config.js";
import { openDatabase } from "../build/backend/db.js";
import { FeedbackLearningService } from "../build/backend/services/FeedbackLearningService.js";

const tempDir = mkdtempSync(path.join(tmpdir(), "jolt-recent-precision-"));
const dbPath = path.join(tempDir, "app.sqlite");
const configPath = path.join(tempDir, "config.json");
writeFileSync(
  configPath,
  JSON.stringify(
    {
      server: {
        database_driver: "sqlite",
        database_path: dbPath
      }
    },
    null,
    2
  )
);
process.env.CONFIG_PATH = configPath;

const db = openDatabase(loadConfig());
try {
  db.prepare(`
    INSERT INTO repositories (
      id, project_id, provider, external_repo_id, name, default_branch, status, provider_config_json
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    "repo_recent_precision",
    "project_recent_precision",
    "github",
    "recent-precision",
    "recent precision",
    "main",
    "active",
    "{}"
  );
  db.prepare(`
    INSERT INTO merge_requests (
      id, repository_id, external_mr_id, number, title, author, source_branch, target_branch,
      review_status, latest_head_sha, html_url, metadata_json
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run("mr_recent_precision", "repo_recent_precision", "1", 1, "recent precision", "tester", "feature", "main", "pending", "head", "", "{}");
  db.prepare(`
    INSERT INTO review_jobs (id, merge_request_id, head_sha, status)
    VALUES (?, ?, ?, ?)
  `).run("job_recent_precision", "mr_recent_precision", "head", "completed");
  db.prepare(`
    INSERT INTO review_runs (id, review_job_id, effort_level, status)
    VALUES (?, ?, ?, ?)
  `).run("run_recent_precision", "job_recent_precision", "standard", "completed");
  db.prepare(`
    INSERT INTO review_findings (
      id, review_run_id, severity, confidence, agent_id, head_sha, dedupe_hash,
      file_path, line_start, line_end, title, problem_description, recommendation,
      suggested_code, evidence, covered_rules_json
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    "finding_recent_precision",
    "run_recent_precision",
    "medium",
    0.8,
    "security_agent",
    "head",
    "dedupe_recent",
    "src/Auth.java",
    10,
    10,
    "测试问题",
    "测试描述",
    "测试建议",
    "return;",
    "测试证据",
    JSON.stringify(["SEC-RECENT-001"])
  );

  const service = new FeedbackLearningService(db);
  service.recordFeedback({
    userId: "local_admin",
    finding: {
      id: "finding_recent_precision",
      agent_id: "security_agent",
      dedupe_hash: "dedupe_recent",
      covered_rules_json: JSON.stringify(["SEC-RECENT-001"]),
      project_id: "project_recent_precision"
    },
    feedbackType: "accepted",
    scope: "project"
  });
  service.recordFeedback({
    userId: "local_admin",
    finding: {
      id: "finding_recent_precision",
      agent_id: "security_agent",
      dedupe_hash: "dedupe_recent",
      covered_rules_json: JSON.stringify(["SEC-RECENT-001"]),
      project_id: "project_recent_precision"
    },
    feedbackType: "false_positive",
    scope: "project"
  });
  db.prepare("UPDATE user_feedback SET created_at = ? WHERE feedback_type = 'accepted'").run("2026-05-17T00:00:00.000Z");
  db.prepare("UPDATE user_feedback SET created_at = ? WHERE feedback_type = 'false_positive'").run("2026-03-14T00:00:00.000Z");

  let history = db.prepare(`
    SELECT accepted_count, rejected_count, recent_accepted_count, recent_rejected_count
    FROM rule_precision_history
    WHERE project_id = ? AND agent_id = ? AND rule_id = ?
  `).get("project_recent_precision", "security_agent", "SEC-RECENT-001");
  if (!history || Number(history.accepted_count) !== 1 || Number(history.rejected_count) !== 1) {
    throw new Error(`lifetime counts were not updated: ${JSON.stringify(history)}`);
  }
  if (Number(history.recent_accepted_count) !== 0 || Number(history.recent_rejected_count) !== 0) {
    throw new Error(`recent counts must not be incremented on write path: ${JSON.stringify(history)}`);
  }

  const result = service.recalculateRecentPrecision({
    projectId: "project_recent_precision",
    windowDays: 90,
    now: new Date("2026-06-17T00:00:00.000Z")
  });
  history = db.prepare(`
    SELECT accepted_count, rejected_count, recent_accepted_count, recent_rejected_count, auto_suppress
    FROM rule_precision_history
    WHERE project_id = ? AND agent_id = ? AND rule_id = ?
  `).get("project_recent_precision", "security_agent", "SEC-RECENT-001");
  if (Number(history.accepted_count) !== 1 || Number(history.rejected_count) !== 1) {
    throw new Error(`lifetime counts changed during recalc: ${JSON.stringify(history)}`);
  }
  if (Number(history.recent_accepted_count) !== 1 || Number(history.recent_rejected_count) !== 0) {
    throw new Error(`90-day recent counts are wrong: ${JSON.stringify(history)}`);
  }
  console.log(JSON.stringify({ ok: true, result, history }, null, 2));
} finally {
  db.close?.();
}
