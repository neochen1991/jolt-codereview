import { DatabaseSync } from "node:sqlite";
import path from "node:path";
import { loadConfig, root } from "./config-utils.mjs";

const DEFAULT_MR_IDS = [
  "mr_repo_github_java-controller-risk_9201",
  "mr_repo_github_java-dependency-risk_9202",
  "mr_repo_github_java-config-risk_9203",
  "mr_repo_github_java-db-migration-risk_9204",
  "mr_repo_github_java-ddd-risk_9205",
];

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

const mrIdsArg = process.argv.find((arg) => arg.startsWith("--mr-ids="));
const mrIds = ((mrIdsArg ? mrIdsArg.slice("--mr-ids=".length) : process.env.MR_IDS) || DEFAULT_MR_IDS.join(","))
  .split(",")
  .map((item) => item.trim())
  .filter(Boolean);

const db = new DatabaseSync(dbPath());
const perMr = [];
let expectedTotal = 0;
let matchedTotal = 0;
let findingTotal = 0;
let falsePositiveTotal = 0;
const aggregateMatchedRules = new Set();
const aggregateMissingRules = new Set();
const aggregateUnknown = [];

for (const mrId of mrIds) {
  const mr = db.prepare("SELECT * FROM merge_requests WHERE id = ?").get(mrId);
  if (!mr) throw new Error(`MR not found: ${mrId}`);
  const metadata = asJson(mr.metadata_json, {});
  const expected = new Set((metadata.expected_issues || []).map(normalizeRule).filter(Boolean));
  const run = db.prepare(`
    SELECT rr.*
    FROM review_runs rr
    JOIN review_jobs rj ON rj.id = rr.review_job_id
    WHERE rj.merge_request_id = ?
    ORDER BY rr.started_at DESC
    LIMIT 1
  `).get(mrId);
  if (!run) throw new Error(`MR has no review run: ${mrId}`);
  const findings = db.prepare(`
    SELECT *
    FROM review_findings
    WHERE review_run_id = ?
    ORDER BY selected DESC, severity DESC, confidence DESC, created_at
  `).all(run.id);
  const coveredRules = new Set();
  const finalFindings = findings.map((finding) => {
    const rules = asJson(finding.covered_rules_json, []).map(normalizeRule).filter(Boolean);
    for (const rule of rules) coveredRules.add(rule);
    return {
      id: finding.id,
      agent_id: finding.agent_id,
      severity: finding.severity,
      confidence: finding.confidence,
      title: finding.title,
      file_path: finding.file_path,
      line_start: finding.line_start,
      covered_rules: rules,
      has_trace: asJson(finding.quality_trace_json, null) !== null,
      has_tools: asJson(finding.tool_provenance_json, []).length > 0,
      has_suggested_code: Boolean(String(finding.suggested_code || "").trim()),
    };
  });
  const matched = [...expected].filter((rule) => coveredRules.has(rule));
  const missing = [...expected].filter((rule) => !coveredRules.has(rule));
  const unknown = finalFindings.filter((finding) => !finding.covered_rules.some((rule) => expected.has(rule)));
  for (const rule of matched) aggregateMatchedRules.add(rule);
  for (const rule of missing) aggregateMissingRules.add(rule);
  for (const item of unknown) aggregateUnknown.push({ mr_id: mrId, ...item });
  expectedTotal += expected.size;
  matchedTotal += matched.length;
  findingTotal += finalFindings.length;
  falsePositiveTotal += unknown.length;
  perMr.push({
    mr_id: mrId,
    run_id: run.id,
    status: run.status,
    expected_count: expected.size,
    finding_count: finalFindings.length,
    matched_count: matched.length,
    missing_count: missing.length,
    false_positive_count: unknown.length,
    recall: expected.size ? Number((matched.length / expected.size).toFixed(4)) : 1,
    fp_rate: finalFindings.length ? Number((unknown.length / finalFindings.length).toFixed(4)) : 0,
    matched,
    missing,
    unknown_findings: unknown,
    trace_complete: finalFindings.every((item) => item.has_trace && item.has_suggested_code),
    tool_trace_count: finalFindings.filter((item) => item.has_tools).length,
  });
}

db.close();

const report = {
  mr_count: mrIds.length,
  expected_total: expectedTotal,
  finding_total: findingTotal,
  matched_total: matchedTotal,
  missing_total: expectedTotal - matchedTotal,
  false_positive_total: falsePositiveTotal,
  recall: expectedTotal ? Number((matchedTotal / expectedTotal).toFixed(4)) : 1,
  fp_rate: findingTotal ? Number((falsePositiveTotal / findingTotal).toFixed(4)) : 0,
  unique_matched_rules: [...aggregateMatchedRules].sort(),
  unique_missing_rules: [...aggregateMissingRules].sort(),
  unknown_findings: aggregateUnknown,
  per_mr: perMr,
};

console.log(JSON.stringify(report, null, 2));
if (report.recall < 0.9) throw new Error(`5MR recall below target: ${report.recall}`);
if (report.fp_rate > 0.1) throw new Error(`5MR false positive rate above target: ${report.fp_rate}`);
if (!perMr.every((item) => item.trace_complete)) throw new Error("some findings lack trace or suggested code");
