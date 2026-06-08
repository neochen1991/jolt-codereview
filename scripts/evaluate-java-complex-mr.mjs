import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { loadConfig, root } from "./config-utils.mjs";

const DEFAULT_MR_ID = process.env.MR_ID || "mr_repo_github_java_complex_10file_9301";
const MIN_RECALL = Number(process.env.MIN_RECALL || "0.9");
const MAX_FALSE_POSITIVE_RATE = Number(process.env.MAX_FP_RATE || "0.1");
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

function formatPercent(value) {
  return `${(value * 100).toFixed(1)}%`;
}

function ruleIntersection(rules, expected) {
  return rules.filter((rule) => expected.has(rule));
}

function findingText(finding) {
  return [
    finding.title,
    finding.problem_description,
    finding.evidence,
    finding.recommendation,
    finding.suggested_code,
  ]
    .filter(Boolean)
    .join("\n")
    .toLowerCase();
}

function expectedKeyword(expected) {
  const text = `${expected.title || ""} ${expected.rule_id || ""}`.toLowerCase();
  if (text.includes("fastjson")) return "fastjson";
  if (text.includes("paymentroot123")) return "paymentroot123";
  if (text.includes("drop column")) return "drop column";
  if (text.includes("redis keys") || text.includes("keys 命令")) return "keys";
  if (text.includes("ttl")) return "ttl";
  if (text.includes("map<string,object>")) return "map<string, object>";
  if (text.includes("@valid")) return "@valid";
  if (text.includes("string.valueof")) return "string.valueof";
  if (text.includes("sql")) return "sql";
  return "";
}

function matchesExpectedFinding(finding, expected) {
  if (!finding.covered_rules.includes(expected.rule_id)) return false;
  if (expected.file_path && finding.file_path && finding.file_path !== expected.file_path) return false;
  if (expected.line_start && finding.line_start) {
    const distance = Math.abs(Number(finding.line_start) - Number(expected.line_start));
    if (distance > 5) return false;
  }
  const keyword = expectedKeyword(expected);
  if (expected.rule_id === "DDD-VO-002") {
    const text = findingText(finding).replace(/\s+/g, "");
    if (!text.includes("map<string,object>")) return false;
  } else if (keyword && !findingText(finding).includes(keyword)) {
    return false;
  }
  return true;
}

function hasActionableSuggestedCode(value) {
  const text = String(value || "").trim();
  if (!text) return false;
  const lowered = text.toLowerCase();
  return ![
    "根据当前文件上下文",
    "在命中行附近按工具规则修改实现",
    "重新运行对应静态工具确认",
    "按以下方向调整",
  ].some((marker) => lowered.includes(marker.toLowerCase()));
}

function renderMarkdown(report) {
  const lines = [
    "# Java Complex 10-File MR Review Quality Report",
    "",
    `- MR: ${report.mr_id}`,
    `- Review Run: ${report.run_id}`,
    `- Run Status: ${report.run_status}`,
    `- Expected Issues: ${report.expected_count}`,
    `- Final Findings: ${report.finding_count}`,
    `- Strict Matched Issues: ${report.strict_matched_count}`,
    `- Strict Missing Issues: ${report.strict_missing_count}`,
    `- Strict False Positive Findings: ${report.strict_false_positive_count}`,
    `- Strict Recall: ${formatPercent(report.strict_recall)}`,
    `- Strict False Positive Rate: ${formatPercent(report.strict_fp_rate)}`,
    `- Rule-Level Matched Issues: ${report.rule_matched_count}`,
    `- Rule-Level Recall: ${formatPercent(report.rule_recall)}`,
    `- Meets Target: ${report.meets_target ? "yes" : "no"}`,
    `- Trace Complete: ${report.trace_complete ? "yes" : "no"}`,
    `- Suggested Code Complete: ${report.suggested_code_complete ? "yes" : "no"}`,
    "",
    "## Expected Issue Coverage",
    "",
    "| Rule | Status | File | Line | Title |",
    "| --- | --- | --- | ---: | --- |",
  ];

  for (const item of report.expected_issues) {
    lines.push(`| ${item.rule_id} | ${item.strict_matched ? "matched" : "missing"} | ${item.file_path} | ${item.line_start} | ${item.title} |`);
  }

  lines.push("", "## Final Findings", "", "| Rule(s) | Severity | Confidence | Agent | File | Line | Title | Tool Count |", "| --- | --- | ---: | --- | --- | ---: | --- | ---: |");
  for (const finding of report.findings) {
    lines.push(
      `| ${finding.covered_rules.join(", ") || "-"} | ${finding.severity} | ${finding.confidence} | ${finding.agent_id} | ${finding.file_path || "-"} | ${finding.line_start || "-"} | ${finding.title} | ${finding.tool_provenance_count} |`
    );
  }

  lines.push("", "## Missing Rules");
  if (report.strict_missing.length === 0) {
    lines.push("", "None.");
  } else {
    for (const rule of report.strict_missing) lines.push(`- ${rule}`);
  }

  lines.push("", "## False Positive Candidates");
  if (report.strict_false_positive_findings.length === 0) {
    lines.push("", "None.");
  } else {
    for (const finding of report.strict_false_positive_findings) {
      lines.push(`- ${finding.title} (${finding.file_path || "-"}:${finding.line_start || "-"}) rules=${finding.covered_rules.join(", ") || "-"}`);
    }
  }

  lines.push("", "## Tool Coverage", "", "| Tool | Calls | Completed | Skipped | Failed | Hits | Rules Hit | Files Hit | Duration ms |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |");
  for (const tool of report.coverage.tools || []) {
    lines.push(
      `| ${tool.id} | ${tool.calls} | ${tool.completed_calls} | ${tool.skipped_calls} | ${tool.failed_calls} | ${tool.hits} | ${tool.rules_hit} | ${tool.files_hit} | ${tool.duration_ms} |`
    );
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

const metadata = asJson(mr.metadata_json, {});
const expectedDetails = Array.isArray(metadata.expected_issue_details) ? metadata.expected_issue_details : [];
const expectedRules = new Set(
  (expectedDetails.length ? expectedDetails.map((item) => item.rule_id) : metadata.expected_issues || [])
    .map(normalizeRule)
    .filter(Boolean)
);

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
  const toolProvenance = asJson(finding.tool_provenance_json, []);
  const qualityTrace = asJson(finding.quality_trace_json, null);
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
    matched_expected_rules: ruleIntersection(coveredRules, expectedRules),
    tool_provenance_count: Array.isArray(toolProvenance) ? toolProvenance.length : 0,
    tool_names: Array.isArray(toolProvenance)
      ? [...new Set(toolProvenance.map((item) => item.tool || item.tool_name || item.name).filter(Boolean))]
      : [],
    has_quality_trace: qualityTrace !== null,
    has_suggested_code: hasActionableSuggestedCode(finding.suggested_code),
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
const ruleMatched = [...expectedRules].filter((rule) => coveredRules.has(rule));
const ruleMissing = [...expectedRules].filter((rule) => !coveredRules.has(rule));
const ruleFalsePositiveFindings = findings.filter((finding) => finding.matched_expected_rules.length === 0);
const strictMatched = expectedIssues.filter((item) => item.strict_matched).map((item) => item.rule_id);
const strictMissing = expectedIssues.filter((item) => !item.strict_matched).map((item) => item.rule_id);
const strictFalsePositiveFindings = findings.filter(
  (finding) => !expectedDetails.some((expected) => matchesExpectedFinding(finding, expected))
);
const ruleRecall = expectedRules.size ? ruleMatched.length / expectedRules.size : 1;
const ruleFpRate = findings.length ? ruleFalsePositiveFindings.length / findings.length : 0;
const strictRecall = expectedRules.size ? strictMatched.length / expectedRules.size : 1;
const strictFpRate = findings.length ? strictFalsePositiveFindings.length / findings.length : 0;

const report = {
  mr_id: DEFAULT_MR_ID,
  run_id: run.id,
  run_status: run.status,
  expected_count: expectedRules.size,
  finding_count: findings.length,
  rule_matched_count: ruleMatched.length,
  rule_missing_count: ruleMissing.length,
  rule_false_positive_count: ruleFalsePositiveFindings.length,
  rule_recall: Number(ruleRecall.toFixed(4)),
  rule_fp_rate: Number(ruleFpRate.toFixed(4)),
  strict_matched_count: strictMatched.length,
  strict_missing_count: strictMissing.length,
  strict_false_positive_count: strictFalsePositiveFindings.length,
  strict_recall: Number(strictRecall.toFixed(4)),
  strict_fp_rate: Number(strictFpRate.toFixed(4)),
  meets_target: strictRecall >= MIN_RECALL && strictFpRate <= MAX_FALSE_POSITIVE_RATE,
  trace_complete: findings.every((item) => item.has_quality_trace),
  suggested_code_complete: findings.every((item) => item.has_suggested_code),
  rule_matched: ruleMatched,
  rule_missing: ruleMissing,
  strict_matched: strictMatched,
  strict_missing: strictMissing,
  expected_issues: expectedIssues,
  findings,
  rule_false_positive_findings: ruleFalsePositiveFindings,
  strict_false_positive_findings: strictFalsePositiveFindings,
  coverage,
  budget,
};

db.close();

const reportDir = path.join(root, "docs", "reports");
mkdirSync(reportDir, { recursive: true });
const reportPath = path.join(reportDir, "2026-06-07-java-complex-10file-mr-quality-report.md");
writeFileSync(reportPath, renderMarkdown(report), "utf8");

console.log(JSON.stringify({ ...report, report_path: reportPath }, null, 2));
if (!TERMINAL_RUN_STATUSES.has(String(run.status))) throw new Error(`review run is not terminal: ${run.status}`);
if (strictRecall < MIN_RECALL) throw new Error(`complex MR strict recall below target: ${report.strict_recall}`);
if (strictFpRate > MAX_FALSE_POSITIVE_RATE) throw new Error(`complex MR strict false positive rate above target: ${report.strict_fp_rate}`);
if (!report.trace_complete) throw new Error("some findings lack quality trace");
if (!report.suggested_code_complete) throw new Error("some findings lack suggested code");
