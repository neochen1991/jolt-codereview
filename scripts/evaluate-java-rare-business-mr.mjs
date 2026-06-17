import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { loadConfig, root } from "./config-utils.mjs";

const DEFAULT_MR_ID = process.env.MR_ID || "mr_repo_github_java_rare_business_9601";
const MIN_RECALL = Number(process.env.MIN_RECALL || "0.5");
const MAX_FALSE_POSITIVE_RATE = Number(process.env.MAX_FP_RATE || "0.5");
const TERMINAL_RUN_STATUSES = new Set(["completed", "waiting_confirmation", "no_issue", "submitted", "failed"]);

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

function evaluateFindingLayer(findings, expectedDetails, expectedRules) {
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
  return {
    covered_rules: [...coveredRules],
    expected_issues: expectedIssues,
    rule_matched: ruleMatched,
    rule_missing: ruleMissing,
    rule_false_positive_findings: ruleFalsePositiveFindings,
    strict_matched: strictMatched,
    strict_missing: strictMissing,
    strict_false_positive_findings: strictFalsePositiveFindings,
    rule_recall: Number(ruleRecall.toFixed(4)),
    rule_fp_rate: Number(ruleFpRate.toFixed(4)),
    strict_recall: Number(strictRecall.toFixed(4)),
    strict_fp_rate: Number(strictFpRate.toFixed(4)),
  };
}

function formatPercent(value) {
  return `${(value * 100).toFixed(1)}%`;
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

function evidenceContractFromTrace(trace) {
  return trace && typeof trace === "object" ? trace.evidence_contract || {} : {};
}

function summarizeRuntime(db, runId, runStatus) {
  const spans = db.prepare(`
    SELECT id, span_key, agent_id, status, started_at, ended_at
    FROM agent_trace_spans
    WHERE review_run_id = ?
    ORDER BY started_at
  `).all(runId);
  const events = db.prepare(`
    SELECT e.event_type, e.summary, e.created_at, s.span_key, s.agent_id
    FROM agent_trace_events e
    JOIN agent_trace_spans s ON s.id = e.span_id
    WHERE s.review_run_id = ?
    ORDER BY e.created_at DESC
    LIMIT 20
  `).all(runId);
  const candidateEvents = db.prepare(`
    SELECT e.summary, e.created_at, s.span_key, s.agent_id
    FROM agent_trace_events e
    JOIN agent_trace_spans s ON s.id = e.span_id
    WHERE s.review_run_id = ? AND e.event_type = 'finding_candidate'
    ORDER BY e.created_at
  `).all(runId).map((event) => {
    const count = Number(String(event.summary || "").match(/产出\s*(\d+)\s*个候选问题/)?.[1] || 0);
    return { ...event, candidate_count: count };
  });
  const staticSummary = db.prepare(`
    SELECT e.summary
    FROM agent_trace_events e
    JOIN agent_trace_spans s ON s.id = e.span_id
    WHERE s.review_run_id = ? AND e.event_type = 'static_tool_summary'
    ORDER BY e.created_at DESC
    LIMIT 1
  `).get(runId);
  const openSpans = spans.filter((span) => span.status !== "completed" && !span.ended_at);
  const reached = new Set(spans.map((span) => span.span_key));
  return {
    terminal: TERMINAL_RUN_STATUSES.has(String(runStatus)),
    reached_verify: reached.has("verify_findings"),
    reached_judge: reached.has("judge_findings"),
    reached_finalize: reached.has("finalize"),
    open_spans: openSpans,
    candidate_event_count: candidateEvents.length,
    candidate_total: candidateEvents.reduce((sum, event) => sum + Number(event.candidate_count || 0), 0),
    candidate_events: candidateEvents,
    static_tool_summary: staticSummary?.summary || "",
    recent_events: events,
  };
}

function renderMarkdown(report) {
  const lines = [
    "# Java Rare Business MR Review Quality Report",
    "",
    `- MR: ${report.mr_id}`,
    `- Review Run: ${report.run_id}`,
    `- Run Status: ${report.run_status}`,
    `- Expected Issues: ${report.expected_count}`,
    `- Candidate Findings: ${report.candidate_count}`,
    `- Candidate Strict Recall: ${formatPercent(report.candidate_strict_recall)}`,
    `- Candidate Strict False Positive Rate: ${formatPercent(report.candidate_strict_fp_rate)}`,
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
    `- Evidence Contract Complete: ${report.evidence_contract_complete ? "yes" : "no"}`,
    `- Evidence Contract Avg Score: ${formatPercent(report.evidence_contract_average_score)}`,
    `- Evidence Contract Risk: ${report.evidence_contract_summary.quality_risk || "unknown"}`,
    "",
    "## Runtime Diagnosis",
    "",
    `- Terminal Run: ${report.runtime.terminal ? "yes" : "no"}`,
    `- Reached Verify: ${report.runtime.reached_verify ? "yes" : "no"}`,
    `- Reached Judge: ${report.runtime.reached_judge ? "yes" : "no"}`,
    `- Reached Finalize: ${report.runtime.reached_finalize ? "yes" : "no"}`,
    `- Static Tool Summary: ${report.runtime.static_tool_summary || "-"}`,
    `- Expert Candidate Events: ${report.runtime.candidate_event_count}`,
    `- Expert Candidate Total: ${report.runtime.candidate_total}`,
  ];
  if (!report.runtime.terminal) {
    lines.push(
      "- Interpretation: the review did not reach finalization, so Final Findings reflects an incomplete run rather than a completed review result.",
    );
  }
  if (report.runtime.open_spans.length) {
    lines.push("- Open Spans:");
    for (const span of report.runtime.open_spans) {
      lines.push(`  - ${span.span_key}${span.agent_id ? ` (${span.agent_id})` : ""}, status=${span.status}, started_at=${span.started_at}`);
    }
  }
  if (report.runtime.candidate_events.length) {
    lines.push("", "### Expert Candidate Events", "", "| Agent | Candidates | Time | Summary |", "| --- | ---: | --- | --- |");
    for (const event of report.runtime.candidate_events) {
      lines.push(`| ${event.agent_id || event.span_key} | ${event.candidate_count} | ${event.created_at} | ${event.summary} |`);
    }
  }
  lines.push(
    "",
    "### Recent Trace Events",
    "",
    "| Time | Span | Event | Summary |",
    "| --- | --- | --- | --- |",
  );
  for (const event of report.runtime.recent_events) {
    lines.push(`| ${event.created_at} | ${event.span_key} | ${event.event_type} | ${event.summary} |`);
  }

  lines.push(
    "",
    "## Expected Issue Coverage",
    "",
    "| Rule | Status | File | Line | Title |",
    "| --- | --- | --- | ---: | --- |",
  );
  for (const item of report.expected_issues) {
    const candidateStatus = report.candidate_expected_issues.find((candidate) => candidate.rule_id === item.rule_id)?.strict_matched
      ? "candidate"
      : "missing";
    lines.push(`| ${item.rule_id} | final=${item.strict_matched ? "matched" : "missing"} / ${candidateStatus} | ${item.file_path} | ${item.line_start} | ${item.title} |`);
  }

  lines.push(
    "",
    "## Candidate Findings",
    "",
    "| Stage | Status | Rule(s) | Severity | Confidence | Source | File | Line | Title |",
    "| --- | --- | --- | --- | ---: | --- | --- | ---: | --- |",
  );
  for (const finding of report.candidate_findings) {
    lines.push(
      `| ${finding.stage || "-"} | ${finding.status || "-"} | ${finding.covered_rules.join(", ") || "-"} | ${finding.severity || "-"} | ${finding.confidence} | ${finding.agent_id || finding.tool_name || finding.source_type || "-"} | ${finding.file_path || "-"} | ${finding.line_start || "-"} | ${finding.title} |`
    );
  }

  lines.push("", "## Candidate To Final Loss");
  const lost = report.candidate_strict_matched.filter((rule) => !report.strict_matched.includes(rule));
  if (lost.length === 0) {
    lines.push("", "None.");
  } else {
    for (const rule of lost) lines.push(`- ${rule}`);
  }

  lines.push("", "## Final Findings", "", "| Rule(s) | Severity | Confidence | Agent | File | Line | Title | Tool Count | Evidence Contract |", "| --- | --- | ---: | --- | --- | ---: | --- | ---: | --- |");
  for (const finding of report.findings) {
    lines.push(
      `| ${finding.covered_rules.join(", ") || "-"} | ${finding.severity} | ${finding.confidence} | ${finding.agent_id} | ${finding.file_path || "-"} | ${finding.line_start || "-"} | ${finding.title} | ${finding.tool_provenance_count} | ${finding.evidence_contract_status}:${formatPercent(finding.evidence_contract_score)} |`
    );
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

const candidateRows = db.prepare(`
  SELECT *
  FROM candidate_findings
  WHERE review_run_id = ?
    AND stage IN ('verifier', 'tool_promotion', 'bound_rule_supplement', 'judge')
  ORDER BY
    CASE status WHEN 'final' THEN 0 WHEN 'accepted' THEN 1 WHEN 'candidate' THEN 2 ELSE 3 END,
    confidence DESC,
    created_at
`).all(run.id);

const findings = rows.map((finding) => {
  const coveredRules = asJson(finding.covered_rules_json, []).map(normalizeRule).filter(Boolean);
  const toolProvenance = asJson(finding.tool_provenance_json, []);
  const qualityTrace = asJson(finding.quality_trace_json, null);
  const contract = evidenceContractFromTrace(qualityTrace);
  const contractScore = Number(contract.score || 0);
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
    tool_provenance_count: Array.isArray(toolProvenance) ? toolProvenance.length : 0,
    tool_names: Array.isArray(toolProvenance)
      ? [...new Set(toolProvenance.map((item) => item.tool || item.tool_name || item.name).filter(Boolean))]
      : [],
    has_quality_trace: qualityTrace !== null,
    has_evidence_contract: Boolean(contract.version),
    evidence_contract_status: contract.status || "missing",
    evidence_contract_score: Number.isFinite(contractScore) ? contractScore : 0,
    has_suggested_code: hasActionableSuggestedCode(finding.suggested_code),
  };
});

const candidateSeen = new Set();
const candidateFindings = [];
for (const candidate of candidateRows) {
  const raw = asJson(candidate.raw_json, {});
  const rawRules = Array.isArray(raw.covered_rules) ? raw.covered_rules : [];
  const coveredRules = rawRules.map(normalizeRule).filter(Boolean);
  if (candidate.rule_id && !coveredRules.includes(normalizeRule(candidate.rule_id))) {
    coveredRules.unshift(normalizeRule(candidate.rule_id));
  }
  const key = `${candidate.dedupe_hash || candidate.id}|${coveredRules.join(",")}|${candidate.stage}|${candidate.status}`;
  if (candidateSeen.has(key)) continue;
  candidateSeen.add(key);
  candidateFindings.push({
    id: candidate.id,
    stage: candidate.stage,
    status: candidate.status,
    source_type: candidate.source_type,
    agent_id: candidate.agent_id,
    tool_name: candidate.tool_name,
    severity: candidate.severity,
    confidence: Number(candidate.confidence || 0),
    title: candidate.title || raw.title || "",
    problem_description: candidate.problem_description || raw.problem_description || raw.message || "",
    recommendation: raw.recommendation || "",
    evidence: candidate.evidence || raw.evidence || raw.message || "",
    suggested_code: raw.suggested_code || "",
    file_path: candidate.file_path || raw.file_path || "",
    line_start: candidate.line_start || raw.line_start,
    line_end: candidate.line_end || raw.line_end,
    covered_rules: coveredRules,
    matched_expected_rules: coveredRules.filter((rule) => expectedRules.has(rule)),
    rejected_reasons: asJson(candidate.rejected_reasons_json, []),
  });
}

const finalLayer = evaluateFindingLayer(findings, expectedDetails, expectedRules);
const candidateLayer = evaluateFindingLayer(candidateFindings, expectedDetails, expectedRules);
const evidenceContractAverageScore = findings.length
  ? findings.reduce((sum, item) => sum + item.evidence_contract_score, 0) / findings.length
  : 1;
const evidenceContractSummary = coverage.evidence_contracts || {};
const runtime = summarizeRuntime(db, run.id, run.status);

const report = {
  mr_id: DEFAULT_MR_ID,
  run_id: run.id,
  run_status: run.status,
  expected_count: expectedRules.size,
  candidate_count: candidateFindings.length,
  candidate_rule_matched_count: candidateLayer.rule_matched.length,
  candidate_rule_missing_count: candidateLayer.rule_missing.length,
  candidate_rule_false_positive_count: candidateLayer.rule_false_positive_findings.length,
  candidate_rule_recall: candidateLayer.rule_recall,
  candidate_rule_fp_rate: candidateLayer.rule_fp_rate,
  candidate_strict_matched_count: candidateLayer.strict_matched.length,
  candidate_strict_missing_count: candidateLayer.strict_missing.length,
  candidate_strict_false_positive_count: candidateLayer.strict_false_positive_findings.length,
  candidate_strict_recall: candidateLayer.strict_recall,
  candidate_strict_fp_rate: candidateLayer.strict_fp_rate,
  finding_count: findings.length,
  rule_matched_count: finalLayer.rule_matched.length,
  rule_missing_count: finalLayer.rule_missing.length,
  rule_false_positive_count: finalLayer.rule_false_positive_findings.length,
  rule_recall: finalLayer.rule_recall,
  rule_fp_rate: finalLayer.rule_fp_rate,
  strict_matched_count: finalLayer.strict_matched.length,
  strict_missing_count: finalLayer.strict_missing.length,
  strict_false_positive_count: finalLayer.strict_false_positive_findings.length,
  strict_recall: finalLayer.strict_recall,
  strict_fp_rate: finalLayer.strict_fp_rate,
  meets_target: finalLayer.strict_recall >= MIN_RECALL && finalLayer.strict_fp_rate <= MAX_FALSE_POSITIVE_RATE,
  trace_complete: findings.every((item) => item.has_quality_trace),
  evidence_contract_complete: findings.every((item) => item.has_evidence_contract),
  evidence_contract_average_score: Number(evidenceContractAverageScore.toFixed(4)),
  evidence_contract_summary: evidenceContractSummary,
  suggested_code_complete: findings.every((item) => item.has_suggested_code),
  candidate_rule_matched: candidateLayer.rule_matched,
  candidate_rule_missing: candidateLayer.rule_missing,
  candidate_strict_matched: candidateLayer.strict_matched,
  candidate_strict_missing: candidateLayer.strict_missing,
  candidate_expected_issues: candidateLayer.expected_issues,
  candidate_findings: candidateFindings,
  candidate_rule_false_positive_findings: candidateLayer.rule_false_positive_findings,
  candidate_strict_false_positive_findings: candidateLayer.strict_false_positive_findings,
  rule_matched: finalLayer.rule_matched,
  rule_missing: finalLayer.rule_missing,
  strict_matched: finalLayer.strict_matched,
  strict_missing: finalLayer.strict_missing,
  expected_issues: finalLayer.expected_issues,
  findings,
  rule_false_positive_findings: finalLayer.rule_false_positive_findings,
  strict_false_positive_findings: finalLayer.strict_false_positive_findings,
  coverage,
  budget,
  runtime,
};

db.close();

const reportDir = path.join(root, "docs", "reports");
mkdirSync(reportDir, { recursive: true });
const reportPath = path.join(reportDir, "2026-06-16-java-rare-business-mr-quality-report.md");
writeFileSync(reportPath, renderMarkdown(report), "utf8");

console.log(JSON.stringify({ ...report, report_path: reportPath }, null, 2));
if (!TERMINAL_RUN_STATUSES.has(String(run.status))) throw new Error(`review run is not terminal: ${run.status}`);
if (report.strict_recall < MIN_RECALL) throw new Error(`rare business MR strict recall below target: ${report.strict_recall}`);
if (report.strict_fp_rate > MAX_FALSE_POSITIVE_RATE) throw new Error(`rare business MR strict false positive rate above target: ${report.strict_fp_rate}`);
