import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { loadConfig } from "../build/backend/config.js";
import { openDatabase } from "../build/backend/db.js";
import { FeedbackLearningService } from "../build/backend/services/FeedbackLearningService.js";

const tempDir = mkdtempSync(path.join(tmpdir(), "jolt-suppression-hints-"));
const dbPath = path.join(tempDir, "app.sqlite");
const configPath = path.join(tempDir, "config.json");
writeFileSync(configPath, JSON.stringify({ server: { database_driver: "sqlite", database_path: dbPath } }, null, 2));
process.env.CONFIG_PATH = configPath;

const db = openDatabase(loadConfig());
try {
  const service = new FeedbackLearningService(db);
  const finding = {
    id: "finding_fp_hint",
    review_run_id: "run_hint",
    severity: "medium",
    confidence: 0.8,
    agent_id: "security_agent",
    head_sha: "head",
    dedupe_hash: "dedupe_fp_hint",
    file_path: "src/main/java/demo/AuthController.java",
    line_start: 42,
    line_end: 42,
    title: "误报样例",
    problem_description: "误报样例",
    recommendation: "无",
    suggested_code: "",
    evidence: "return ResponseEntity.ok(Map.of(\"status\", \"ok\"));",
    covered_rules_json: JSON.stringify(["SEC-DEBUG-011"]),
    publish_state: "pending",
    lifecycle_state: "pending",
    selected: 1,
    project_id: "project_hint"
  };
  service.recordFeedback({ userId: "local_admin", finding, feedbackType: "accepted", scope: "project" });
  let rows = db.prepare("SELECT * FROM rule_suppression_hints").all();
  if (rows.length !== 0) throw new Error(`accepted feedback must not create hints: ${JSON.stringify(rows)}`);

  service.recordFeedback({ userId: "local_admin", finding, feedbackType: "false_positive", scope: "project" });
  service.recordFeedback({ userId: "local_admin", finding, feedbackType: "false_positive", scope: "project" });
  rows = db.prepare("SELECT * FROM rule_suppression_hints").all();
  if (rows.length !== 1) throw new Error(`expected one suppression hint: ${JSON.stringify(rows)}`);
  const hint = rows[0];
  if (hint.project_id !== "project_hint" || hint.rule_id !== "SEC-DEBUG-011" || hint.file_glob !== "src/main/**" || Number(hint.count) !== 2) {
    throw new Error(`unexpected hint row: ${JSON.stringify(hint)}`);
  }
  console.log(JSON.stringify({ ok: true, hint }, null, 2));
} finally {
  db.close?.();
}
