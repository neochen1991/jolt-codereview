import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { loadConfig, root } from "./config-utils.mjs";

const GOLD_PATH = path.join(root, "evaluation", "real_gold_set.jsonl");
const OUT_PATH = process.env.REAL_PR_FINDINGS_OUT || path.join(root, "evaluation", "real_findings.jsonl");
const REPORT_PATH = process.env.REAL_PR_EXPORT_REPORT || path.join(root, "evaluation", "real_prs", "latest-export-report.json");
const USABLE_RUN_STATUSES = new Set(["completed", "waiting_confirmation", "no_issue", "submitted"]);

function dbPath() {
  const config = loadConfig();
  return path.resolve(root, config.server?.database_path || "data/jolt-codereview.sqlite");
}

function readJsonl(file) {
  return readFileSync(file, "utf8")
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line));
}

function asJson(value, fallback) {
  try {
    return JSON.parse(value || "");
  } catch {
    return fallback;
  }
}

function normalizeRule(rule) {
  return String(rule || "").trim();
}

const goldItems = readJsonl(GOLD_PATH);
const mrIds = [...new Set(goldItems.map((item) => String(item.mr_id || "").trim()).filter(Boolean))];
if (!mrIds.length) throw new Error("evaluation/real_gold_set.jsonl contains no mr_id values");

const db = new DatabaseSync(dbPath());
const exported = [];
const perMr = [];

for (const mrId of mrIds) {
  const mr = db.prepare("SELECT * FROM merge_requests WHERE id = ?").get(mrId);
  if (!mr) throw new Error(`MR not found for real-pr evaluation: ${mrId}. Seed and review it first.`);
  const runs = db.prepare(`
    SELECT rr.*
    FROM review_runs rr
    JOIN review_jobs rj ON rj.id = rr.review_job_id
    WHERE rj.merge_request_id = ?
    ORDER BY rr.started_at DESC
    LIMIT 10
  `).all(mrId);
  const skippedRuns = runs.filter((item) => !USABLE_RUN_STATUSES.has(String(item.status || "")));
  const run = runs.find((item) => USABLE_RUN_STATUSES.has(String(item.status || "")));
  if (!run) throw new Error(`MR has no review run for real-pr evaluation: ${mrId}. Run an actual review first.`);
  const rows = db.prepare(`
    SELECT *
    FROM review_findings
    WHERE review_run_id = ?
    ORDER BY selected DESC, severity DESC, confidence DESC, created_at
  `).all(run.id);
  for (const finding of rows) {
    exported.push({
      mr_id: mrId,
      merge_request_id: mrId,
      review_run_id: run.id,
      finding_id: finding.id,
      agent_id: finding.agent_id,
      severity: finding.severity,
      confidence: Number(finding.confidence || 0),
      file_path: finding.file_path,
      line_start: finding.line_start,
      line_end: finding.line_end,
      title: finding.title,
      problem_description: finding.problem_description,
      evidence: finding.evidence,
      recommendation: finding.recommendation,
      covered_rules: asJson(finding.covered_rules_json, []).map(normalizeRule).filter(Boolean),
      tool_provenance: asJson(finding.tool_provenance_json, []),
      quality_trace: asJson(finding.quality_trace_json, {})
    });
  }
  perMr.push({
    mr_id: mrId,
    title: mr.title,
    run_id: run.id,
    run_status: run.status,
    skipped_unusable_runs: skippedRuns.map((item) => ({ id: item.id, status: item.status, report_summary: item.report_summary })),
    finding_count: rows.length
  });
}

db.close();
mkdirSync(path.dirname(OUT_PATH), { recursive: true });
writeFileSync(OUT_PATH, exported.map((item) => JSON.stringify(item)).join("\n") + "\n", "utf8");
mkdirSync(path.dirname(REPORT_PATH), { recursive: true });
writeFileSync(REPORT_PATH, JSON.stringify({ exported_findings: exported.length, per_mr: perMr }, null, 2), "utf8");
console.log(JSON.stringify({ out: OUT_PATH, report: REPORT_PATH, exported_findings: exported.length, per_mr: perMr }, null, 2));
