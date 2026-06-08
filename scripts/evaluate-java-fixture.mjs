import { DatabaseSync } from "node:sqlite";
import path from "node:path";
import { loadConfig, root } from "./config-utils.mjs";

const MR_ID = process.env.MR_ID || "mr_repo_github_java_fixture_9101";

function dbPath() {
  const config = loadConfig();
  return path.resolve(root, config.server?.database_path || "data/jolt-codereview.sqlite");
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

const db = new DatabaseSync(dbPath());
const mr = db.prepare("SELECT * FROM merge_requests WHERE id = ?").get(MR_ID);
if (!mr) {
  db.close();
  throw new Error(`MR not found: ${MR_ID}`);
}
const metadata = asJson(mr.metadata_json, {});
const expected = new Set((metadata.expected_issues || []).map(normalizeRule).filter(Boolean));
if (!expected.size) {
  db.close();
  throw new Error(`MR ${MR_ID} has no metadata.expected_issues`);
}

const run = db.prepare(`
  SELECT rr.*
  FROM review_runs rr
  JOIN review_jobs rj ON rj.id = rr.review_job_id
  WHERE rj.merge_request_id = ?
  ORDER BY rr.started_at DESC
  LIMIT 1
`).get(MR_ID);
if (!run) {
  db.close();
  throw new Error(`MR ${MR_ID} has no review run`);
}

const findings = db.prepare(`
  SELECT *
  FROM review_findings
  WHERE review_run_id = ?
  ORDER BY severity DESC, confidence DESC, created_at
`).all(run.id);
const toolObservations = db.prepare("SELECT * FROM tool_observations WHERE review_run_id = ?").all(run.id);
db.close();

const coveredRules = new Set();
const finalFindings = findings.map((finding) => {
  const rules = asJson(finding.covered_rules_json, []).map(normalizeRule).filter(Boolean);
  for (const rule of rules) coveredRules.add(rule);
  return {
    id: finding.id,
    agent_id: finding.agent_id,
    severity: finding.severity,
    confidence: finding.confidence,
    file_path: finding.file_path,
    line_start: finding.line_start,
    title: finding.title,
    covered_rules: rules,
    has_suggested_code: Boolean(String(finding.suggested_code || "").trim()),
  };
});

const matched = [...expected].filter((rule) => coveredRules.has(rule));
const missing = [...expected].filter((rule) => !coveredRules.has(rule));
const unknownFindings = finalFindings.filter((finding) => !finding.covered_rules.some((rule) => expected.has(rule)));
const locationKeys = new Map();
for (const finding of finalFindings) {
  const key = `${finding.covered_rules[0] || finding.title}|${finding.file_path}|${Math.floor(((finding.line_start || 0) - 1) / 5)}`;
  locationKeys.set(key, (locationKeys.get(key) || 0) + 1);
}
const duplicateCount = [...locationKeys.values()].filter((count) => count > 1).reduce((sum, count) => sum + count - 1, 0);
const detectionRate = matched.length / expected.size;
const falsePositiveRate = finalFindings.length ? unknownFindings.length / finalFindings.length : 0;

console.log(JSON.stringify({
  mr_id: MR_ID,
  review_run_id: run.id,
  run_status: run.status,
  mr_status: mr.review_status,
  expected_count: expected.size,
  matched_count: matched.length,
  missing_count: missing.length,
  final_finding_count: finalFindings.length,
  tool_observation_count: toolObservations.length,
  detection_rate: Number(detectionRate.toFixed(4)),
  false_positive_count: unknownFindings.length,
  false_positive_rate: Number(falsePositiveRate.toFixed(4)),
  duplicate_count: duplicateCount,
  matched,
  missing,
  unknown_findings: unknownFindings,
  findings: finalFindings
}, null, 2));
