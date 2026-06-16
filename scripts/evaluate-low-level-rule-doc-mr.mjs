import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { loadConfig, root } from "./config-utils.mjs";

const DEFAULT_MR_ID = process.env.MR_ID || "mr_repo_github_low_level_rule_doc_eval_9401";
const MIN_STRICT_RECALL = Number(process.env.MIN_RECALL || "0.8");
const MAX_STRICT_FP_RATE = Number(process.env.MAX_FP_RATE || "0.2");
const TERMINAL_RUN_STATUSES = new Set(["completed", "waiting_confirmation", "no_issue", "submitted"]);

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

function findingText(finding) {
  return [
    finding.title,
    finding.problem_description,
    finding.evidence,
    finding.recommendation,
    finding.suggested_code,
  ].filter(Boolean).join("\n").toLowerCase();
}

function keywordMatched(finding, expected) {
  const text = findingText(finding);
  const keywords = Array.isArray(expected.keywords) ? expected.keywords : [];
  return keywords.every((keyword) => text.includes(String(keyword).toLowerCase()));
}

function matchesExpectedFinding(finding, expected) {
  if (!finding.covered_rules.includes(expected.rule_id)) return false;
  if (expected.file_path && finding.file_path && finding.file_path !== expected.file_path) return false;
  if (expected.line_start && finding.line_start) {
    const distance = Math.abs(Number(finding.line_start) - Number(expected.line_start));
    if (distance > 6) return false;
  }
  return keywordMatched(finding, expected);
}

function formatPercent(value) {
  return `${(value * 100).toFixed(1)}%`;
}

function renderMarkdown(report) {
  const lines = [
    "# Low-Level Rule Document Binding Review Quality Report",
    "",
    `- MR: ${report.mr_id}`,
    `- Review Run: ${report.run_id}`,
    `- Run Status: ${report.run_status}`,
    `- Bound Document: ${report.bound_document.name} (${report.bound_document.id}, ${report.bound_document.version})`,
    `- Bound Agent: ${report.bound_document.agent_key}`,
    `- Parsed Rule Headings In Document: ${report.bound_document.rule_heading_count}`,
    `- Expected Issues: ${report.expected_count}`,
    `- Final Findings: ${report.finding_count}`,
    `- Strict Matched Issues: ${report.strict_matched_count}`,
    `- Strict Missing Issues: ${report.strict_missing_count}`,
    `- Strict False Positive Findings: ${report.strict_false_positive_count}`,
    `- Strict Recall: ${formatPercent(report.strict_recall)}`,
    `- Strict False Positive Rate: ${formatPercent(report.strict_fp_rate)}`,
    `- Rule-Level Recall: ${formatPercent(report.rule_recall)}`,
    `- Low-Level Agent Findings: ${report.low_level_agent_finding_count}`,
    `- Custom Rule Coverage By Low-Level Agent: ${formatPercent(report.low_level_agent_custom_rule_recall)}`,
    `- Meets Target: ${report.meets_target ? "yes" : "no"}`,
    "",
    "## Expected Rule Coverage",
    "",
    "| Rule | Status | File | Line | Title |",
    "| --- | --- | --- | ---: | --- |",
  ];

  for (const item of report.expected_issues) {
    lines.push(`| ${item.rule_id} | ${item.strict_matched ? "matched" : "missing"} | ${item.file_path} | ${item.line_start} | ${item.title} |`);
  }

  lines.push("", "## Final Findings", "", "| Rule(s) | Severity | Confidence | Agent | File | Line | Title |",
    "| --- | --- | ---: | --- | --- | ---: | --- |");
  for (const finding of report.findings) {
    lines.push(`| ${finding.covered_rules.join(", ") || "-"} | ${finding.severity} | ${finding.confidence} | ${finding.agent_id} | ${finding.file_path || "-"} | ${finding.line_start || "-"} | ${finding.title} |`);
  }

  lines.push("", "## Missing Rules");
  if (report.strict_missing.length === 0) {
    lines.push("", "None.");
  } else {
    for (const rule of report.strict_missing) lines.push(`- ${rule}`);
  }

  lines.push("", "## Strict False Positives");
  if (report.strict_false_positive_findings.length === 0) {
    lines.push("", "None.");
  } else {
    for (const finding of report.strict_false_positive_findings) {
      lines.push(`- ${finding.title} (${finding.agent_id}, ${finding.file_path || "-"}:${finding.line_start || "-"}) rules=${finding.covered_rules.join(", ") || "-"}`);
    }
  }

  lines.push("", "## Budget And Agents", "");
  lines.push(`- Agents Executed: ${(report.coverage.agents_executed || []).join(", ") || "-"}`);
  lines.push(`- LLM Calls: ${report.budget.llm_calls ?? 0}`);
  lines.push(`- Tool Calls: ${report.budget.tool_calls ?? 0}`);
  lines.push(`- Wall Seconds: ${report.budget.wall_seconds ?? "-"}`);
  lines.push(`- Truncated Reason: ${report.budget.truncated_reason || "none"}`);

  return `${lines.join("\n")}\n`;
}

const db = new DatabaseSync(dbPath());
const mr = db.prepare("SELECT * FROM merge_requests WHERE id = ?").get(DEFAULT_MR_ID);
if (!mr) throw new Error(`MR not found: ${DEFAULT_MR_ID}`);
const repo = db.prepare("SELECT project_id FROM repositories WHERE id = ?").get(mr.repository_id);
const projectId = String(repo?.project_id || "project_default");

const metadata = asJson(mr.metadata_json, {});
const expectedDetails = Array.isArray(metadata.expected_issue_details) ? metadata.expected_issue_details : [];
const expectedRules = new Set(expectedDetails.map((item) => normalizeRule(item.rule_id)).filter(Boolean));
const ruleDocumentId = String(metadata.rule_document_id || "");
const binding = db.prepare(`
  SELECT rd.id, rd.name, rd.version, rd.status, rd.content, erb.agent_key, erb.priority
  FROM rule_documents rd
  JOIN expert_rule_bindings erb ON erb.rule_document_id = rd.id
  WHERE rd.id = ?
    AND erb.project_id = ?
    AND erb.agent_key = 'low_level_defect_agent'
`).get(ruleDocumentId, projectId);
if (!binding) throw new Error(`low_level_defect_agent is not bound to rule document: ${ruleDocumentId}`);

const run = db.prepare(`
  SELECT rr.*
  FROM review_runs rr
  JOIN review_jobs rj ON rj.id = rr.review_job_id
  WHERE rj.merge_request_id = ?
  ORDER BY rr.started_at DESC
  LIMIT 1
`).get(DEFAULT_MR_ID);
if (!run) throw new Error(`MR has no review run: ${DEFAULT_MR_ID}`);

const coverage = asJson(run.coverage_json, {});
const budget = asJson(run.budget_used_json, {});
const rows = db.prepare(`
  SELECT *
  FROM review_findings
  WHERE review_run_id = ?
  ORDER BY selected DESC, severity DESC, confidence DESC, created_at
`).all(run.id);

const findings = rows.map((finding) => {
  const coveredRules = asJson(finding.covered_rules_json, []).map(normalizeRule).filter(Boolean);
  return {
    id: finding.id,
    agent_id: finding.agent_id,
    severity: finding.severity,
    confidence: Number(finding.confidence || 0),
    title: finding.title,
    problem_description: finding.problem_description,
    recommendation: finding.recommendation,
    evidence: finding.evidence,
    suggested_code: finding.suggested_code,
    file_path: finding.file_path,
    line_start: finding.line_start,
    line_end: finding.line_end,
    covered_rules: coveredRules,
    matched_expected_rules: coveredRules.filter((rule) => expectedRules.has(rule)),
  };
});

const coveredRules = new Set();
for (const finding of findings) {
  for (const rule of finding.covered_rules) coveredRules.add(rule);
}

const expectedIssues = expectedDetails.map((item) => ({
  ...item,
  rule_matched: coveredRules.has(item.rule_id),
  strict_matched: findings.some((finding) => matchesExpectedFinding(finding, item)),
}));
const strictMatched = expectedIssues.filter((item) => item.strict_matched).map((item) => item.rule_id);
const strictMissing = expectedIssues.filter((item) => !item.strict_matched).map((item) => item.rule_id);
const ruleMatched = [...expectedRules].filter((rule) => coveredRules.has(rule));
const ruleMissing = [...expectedRules].filter((rule) => !coveredRules.has(rule));
const strictFalsePositiveFindings = findings.filter(
  (finding) => !expectedDetails.some((expected) => matchesExpectedFinding(finding, expected))
);
const lowLevelAgentFindings = findings.filter((finding) => finding.agent_id === "low_level_defect_agent");
const lowLevelAgentCustomRules = new Set(
  lowLevelAgentFindings.flatMap((finding) => finding.covered_rules).filter((rule) => expectedRules.has(rule))
);
const strictRecall = expectedRules.size ? strictMatched.length / expectedRules.size : 1;
const strictFpRate = findings.length ? strictFalsePositiveFindings.length / findings.length : 0;
const ruleRecall = expectedRules.size ? ruleMatched.length / expectedRules.size : 1;
const lowLevelAgentCustomRuleRecall = expectedRules.size ? lowLevelAgentCustomRules.size / expectedRules.size : 1;

const report = {
  mr_id: DEFAULT_MR_ID,
  run_id: run.id,
  run_status: run.status,
  bound_document: {
    id: binding.id,
    name: binding.name,
    version: binding.version,
    status: binding.status,
    agent_key: binding.agent_key,
    priority: binding.priority,
    rule_heading_count: (String(binding.content || "").match(/^##\s+LLDOC-/gm) || []).length,
  },
  expected_count: expectedRules.size,
  finding_count: findings.length,
  strict_matched_count: strictMatched.length,
  strict_missing_count: strictMissing.length,
  strict_false_positive_count: strictFalsePositiveFindings.length,
  strict_recall: Number(strictRecall.toFixed(4)),
  strict_fp_rate: Number(strictFpRate.toFixed(4)),
  rule_matched_count: ruleMatched.length,
  rule_missing_count: ruleMissing.length,
  rule_recall: Number(ruleRecall.toFixed(4)),
  rule_matched: ruleMatched,
  rule_missing: ruleMissing,
  strict_matched: strictMatched,
  strict_missing: strictMissing,
  low_level_agent_finding_count: lowLevelAgentFindings.length,
  low_level_agent_custom_rule_count: lowLevelAgentCustomRules.size,
  low_level_agent_custom_rule_recall: Number(lowLevelAgentCustomRuleRecall.toFixed(4)),
  meets_target: strictRecall >= MIN_STRICT_RECALL && strictFpRate <= MAX_STRICT_FP_RATE && lowLevelAgentCustomRuleRecall >= MIN_STRICT_RECALL,
  expected_issues: expectedIssues,
  findings,
  strict_false_positive_findings: strictFalsePositiveFindings,
  coverage,
  budget,
};

db.close();

const reportDir = path.join(root, "docs", "reports");
mkdirSync(reportDir, { recursive: true });
const reportPath = path.join(reportDir, "2026-06-16-low-level-rule-doc-binding-quality-report.md");
writeFileSync(reportPath, renderMarkdown(report), "utf8");

console.log(JSON.stringify({ ...report, report_path: reportPath }, null, 2));
if (!TERMINAL_RUN_STATUSES.has(String(run.status))) throw new Error(`review run is not terminal: ${run.status}`);
if (strictRecall < MIN_STRICT_RECALL) throw new Error(`low-level rule doc strict recall below target: ${report.strict_recall}`);
if (strictFpRate > MAX_STRICT_FP_RATE) throw new Error(`low-level rule doc strict false positive rate above target: ${report.strict_fp_rate}`);
if (lowLevelAgentCustomRuleRecall < MIN_STRICT_RECALL) {
  throw new Error(`low-level agent custom rule recall below target: ${report.low_level_agent_custom_rule_recall}`);
}
