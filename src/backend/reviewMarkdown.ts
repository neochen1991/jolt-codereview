import type { FindingRow } from "./types.js";

type JsonRecord = Record<string, unknown>;

type MarkdownMr = {
  id: string;
  repository_name?: string;
  provider?: string;
  number: number;
  title: string;
  author: string;
  source_branch: string;
  target_branch: string;
  review_status: string;
  risk_score: number;
  latest_head_sha: string;
  html_url: string;
};

type MarkdownRun = {
  id: string;
  status: string;
  effort_level?: string;
  report_summary?: string | null;
  started_at?: string;
  completed_at?: string | null;
};

export interface MrReviewMarkdownInput {
  mr: MarkdownMr;
  run?: MarkdownRun | null;
  findings: FindingRow[];
}

function parseJsonArray(value: string | null | undefined): unknown[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function parseJsonObject(value: string | null | undefined): JsonRecord {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as JsonRecord : {};
  } catch {
    return {};
  }
}

function inlineCode(value: unknown) {
  const text = String(value ?? "").trim();
  return text ? `\`${text.replace(/`/g, "\\`")}\`` : "`-`";
}

function listInline(values: unknown[]) {
  return values.length ? values.map(inlineCode).join("、") : "`-`";
}

function severityText(severity: string) {
  const map: Record<string, string> = {
    critical: "严重",
    high: "高危",
    medium: "中危",
    low: "低危",
    info: "提示"
  };
  return map[severity] ?? severity;
}

function agentText(agentId: string) {
  const map: Record<string, string> = {
    security_agent: "Security Agent",
    performance_agent: "Performance Agent",
    coding_agent: "General Coding Agent",
    ddd_agent: "DDD Design Agent",
    frontend_agent: "Frontend Agent",
    test_agent: "Test Agent",
    redis_agent: "Redis Agent",
    dependency_agent: "Dependency Agent",
    database_agent: "Database Agent",
    backend_agent: "Backend Agent",
    low_level_defect_agent: "低级缺陷 Agent"
  };
  return map[agentId] ?? agentId;
}

function locationText(finding: Pick<FindingRow, "file_path" | "line_start" | "line_end">) {
  if (!finding.line_start) return finding.file_path;
  if (finding.line_end && finding.line_end !== finding.line_start) {
    return `${finding.file_path}:${finding.line_start}-${finding.line_end}`;
  }
  return `${finding.file_path}:${finding.line_start}`;
}

function languageForPath(filePath: string) {
  const lower = filePath.toLowerCase();
  if (lower.endsWith(".java")) return "java";
  if (lower.endsWith(".py")) return "python";
  if (lower.endsWith(".ts") || lower.endsWith(".tsx")) return "typescript";
  if (lower.endsWith(".js") || lower.endsWith(".jsx")) return "javascript";
  if (lower.endsWith(".sql")) return "sql";
  if (lower.endsWith(".yml") || lower.endsWith(".yaml")) return "yaml";
  if (lower.endsWith(".json")) return "json";
  if (lower.endsWith(".xml") || lower.endsWith(".pom")) return "xml";
  return "";
}

function fencedCode(filePath: string, code: string) {
  const safeCode = String(code || "").replace(/```/g, "'''").trim();
  return `\`\`\`${languageForPath(filePath)}\n${safeCode || "// 未提供代码片段"}\n\`\`\``;
}

function observationLocation(item: JsonRecord) {
  const file = String(item.file_path ?? "").trim();
  const line = item.line_start === undefined || item.line_start === null ? "" : `:${String(item.line_start)}`;
  return file ? `${file}${line}` : "-";
}

function findingSummaryTable(findings: FindingRow[]) {
  const rows = findings.map((finding, index) => (
    `| ${index + 1} | ${severityText(finding.severity)} | ${agentText(finding.agent_id)} | ${finding.confidence.toFixed(2)} | ${inlineCode(locationText(finding))} | ${finding.title} |`
  ));
  return [
    "| # | 风险 | 专家 | 置信度 | 位置 | 标题 |",
    "|---:|---|---|---:|---|---|",
    ...rows
  ].join("\n");
}

function formatToolEvidence(finding: FindingRow) {
  const observations = parseJsonArray(finding.source_observations_json).filter(
    (item): item is JsonRecord => Boolean(item && typeof item === "object" && !Array.isArray(item))
  );
  const provenance = parseJsonArray(finding.tool_provenance_json).filter(
    (item): item is JsonRecord => Boolean(item && typeof item === "object" && !Array.isArray(item))
  );
  const items = observations.length ? observations : provenance;
  if (!items.length) return "- 无静态工具证据，问题由专家直接提出。";
  return items.map((item, index) => {
    const tool = String(item.tool_name ?? item.tool ?? "unknown_tool");
    const rule = item.rule_id === undefined || item.rule_id === null ? "-" : String(item.rule_id);
    const confidence = item.confidence === undefined || item.confidence === null ? "-" : Number(item.confidence).toFixed(2);
    const message = String(item.message ?? item.summary ?? "工具命中候选问题");
    return `${index + 1}. ${inlineCode(tool)} / rule=${inlineCode(rule)} / confidence=${inlineCode(confidence)} / location=${inlineCode(observationLocation(item))}\n   - ${message}`;
  }).join("\n");
}

function formatFindingDetail(finding: FindingRow, index: number) {
  const coveredRules = parseJsonArray(finding.covered_rules_json);
  const skippedRules = parseJsonArray(finding.skipped_rules_json);
  const qualityTrace = parseJsonObject(finding.quality_trace_json);
  return [
    `### ${index + 1}. [${severityText(finding.severity)}] ${finding.title}`,
    "",
    `- **位置**：${inlineCode(locationText(finding))}`,
    `- **检视专家**：${agentText(finding.agent_id)}`,
    `- **置信度**：${finding.confidence.toFixed(2)}`,
    `- **发布状态**：${finding.publish_state}`,
    `- **生命周期状态**：${finding.lifecycle_state}`,
    `- **命中规范**：${listInline(coveredRules)}`,
    skippedRules.length ? `- **已检查未命中规范**：${listInline(skippedRules)}` : "- **已检查未命中规范**：`-`",
    `- **去重指纹**：${inlineCode(qualityTrace.dedupe_hash ?? finding.dedupe_hash)}`,
    "",
    "#### 问题描述",
    "",
    finding.problem_description || "-",
    "",
    "#### 问题代码详情",
    "",
    fencedCode(finding.file_path, finding.evidence || locationText(finding)),
    "",
    "#### 建议修改方案",
    "",
    finding.recommendation || "-",
    "",
    "#### 建议修改代码",
    "",
    fencedCode(finding.file_path, finding.suggested_code || "// 当前 finding 未提供明确代码片段，请重新检视生成建议修改代码。"),
    "",
    "#### 工具证据",
    "",
    formatToolEvidence(finding)
  ].join("\n");
}

export function markdownFilename(mr: MarkdownMr) {
  const safeTitle = String(mr.title || "mr-review")
    .replace(/[\\/:*?"<>|#\s]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60);
  return `jolt-mr-${mr.number}-${safeTitle || "review"}.md`;
}

export function formatMrReviewMarkdown(input: MrReviewMarkdownInput) {
  const { mr, run, findings } = input;
  const highCount = findings.filter((finding) => ["critical", "high"].includes(finding.severity)).length;
  const selectedCount = findings.filter((finding) => finding.selected).length;
  return [
    "# Jolt CodeReview 检视报告",
    "",
    `> 导出对象：!${mr.number} ${mr.title}`,
    "",
    "## MR 信息",
    "",
    `- **仓库**：${mr.repository_name || "-"}`,
    `- **数据源**：${mr.provider || "-"}`,
    `- **分支**：${inlineCode(mr.source_branch)} -> ${inlineCode(mr.target_branch)}`,
    `- **作者**：${mr.author || "-"}`,
    `- **状态**：${mr.review_status}`,
    `- **风险分**：${mr.risk_score}`,
    `- **Head SHA**：${inlineCode(mr.latest_head_sha)}`,
    `- **链接**：${mr.html_url || "-"}`,
    run ? `- **检视 Run**：${inlineCode(run.id)} / ${run.status}${run.effort_level ? ` / ${run.effort_level}` : ""}` : "- **检视 Run**：-",
    run?.report_summary ? `- **检视摘要**：${run.report_summary}` : "",
    "",
    "## 问题总览",
    "",
    `- **问题总数**：${findings.length}`,
    `- **高危/严重**：${highCount}`,
    `- **已选中**：${selectedCount}`,
    "",
    findings.length ? findingSummaryTable(findings) : "> 当前 MR 没有检视问题。",
    "",
    "## 问题详情",
    "",
    ...(findings.length ? findings.flatMap((finding, index) => [formatFindingDetail(finding, index), ""]) : ["> 当前 MR 没有检视问题。", ""]),
    "## 导出说明",
    "",
    "本报告由 Jolt CodeReview 根据页面当前 MR 检视结果生成，包含问题详情、规则命中、工具证据、代码位置和建议修改代码。"
  ].filter((line) => line !== "").join("\n");
}
