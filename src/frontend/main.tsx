import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Bot,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Circle,
  Clock3,
  Code2,
  Database,
  FileDown,
  FileCode2,
  Filter,
  Folder,
  GitBranch,
  Link2,
  Loader2,
  LockKeyhole,
  RefreshCw,
  Search,
  Send,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  Wrench,
  UserRound,
  Users,
  Zap
} from "lucide-react";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8011";
const DEFAULT_PROJECT_ID = "project_default";
type ViewKey = "mr" | "full" | "issues" | "rules" | "agents" | "repos" | "policy" | "users" | "tools" | "queue" | "settings";

let authToken = typeof window !== "undefined" ? window.localStorage.getItem("jolt_auth_token") : null;

function setApiToken(token: string | null) {
  authToken = token;
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem("jolt_auth_token", token);
  else window.localStorage.removeItem("jolt_auth_token");
}

type User = {
  id: string;
  username: string;
  display_name: string;
};

type Project = {
  id: string;
  name: string;
  description?: string;
  role?: string;
};

type Repo = {
  id: string;
  provider: string;
  external_repo_id: string;
  name: string;
  default_branch: string;
  status: string;
};

type MergeRequest = {
  id: string;
  repository_id: string;
  repository_name: string;
  provider: string;
  external_repo_id?: string;
  external_mr_id: string;
  number: number;
  title: string;
  author: string;
  source_branch: string;
  target_branch: string;
  review_status: string;
  risk_score: number;
  latest_head_sha: string;
  html_url: string;
  updated_at: string;
  finding_count: number;
  latest_run_status?: string;
};

type Finding = {
  id: string;
  severity: string;
  confidence: number;
  agent_id: string;
  file_path: string;
  line_start: number | null;
  line_end: number | null;
  title: string;
  problem_description: string;
  recommendation: string;
  suggested_code?: string;
  evidence: string;
  covered_rules_json?: string;
  skipped_rules_json?: string;
  tool_provenance_json?: string;
  source_observations_json?: string;
  quality_trace_json?: string;
  selected: number;
  publish_state: string;
  lifecycle_state: string;
};

type MrActionState = "start" | "pause" | "stop" | "rerun";

type RuleDetail = {
  rule_id: string;
  title: string;
  document_name?: string;
  version?: string;
  sections?: Record<string, string>;
  raw_excerpt?: string;
  missing?: boolean;
};

type Detail = {
  mr: MergeRequest & { external_repo_id: string };
  jobs: Array<Record<string, unknown>>;
  runs: Array<Record<string, unknown>>;
  findings: Finding[];
  compare?: {
    base_run: Record<string, unknown> | null;
    head_run: Record<string, unknown> | null;
    added: Finding[];
    resolved: Finding[];
    retained: Finding[];
  };
  tool_observations?: Array<Record<string, unknown>>;
  trace: Array<Record<string, unknown>>;
  session_logs?: {
    messages: Array<Record<string, unknown>>;
    tool_calls: Array<Record<string, unknown>>;
    llm_calls: Array<Record<string, unknown>>;
    mcp_calls: Array<Record<string, unknown>>;
    artifacts: Array<Record<string, unknown>>;
  };
};

type MrChangedFile = {
  filename: string;
  status?: string;
  additions?: number;
  deletions?: number;
  patch?: string;
  previous_filename?: string;
};

type ParsedDiffLine = {
  kind: "context" | "add" | "del" | "meta";
  oldLine: number | null;
  newLine: number | null;
  content: string;
};

type StaticToolAvailabilityItem = {
  name: string;
  displayName: string;
  category: string;
  requiredFor: string;
  available: boolean;
  status: string;
  path: string | null;
  version: string | null;
  installHint: string;
};

type StaticToolAvailability = {
  platform: string;
  os: string;
  path_delimiter: string;
  checked_at: string;
  total: number;
  available_count: number;
  missing_count: number;
  items: StaticToolAvailabilityItem[];
};

type LlmSettingsForm = {
  default_provider: string;
  default_base_url: string;
  default_model: string;
  default_api_key_env: string;
  default_api_key: string;
  request_timeout_seconds: string;
  max_output_tokens: string;
  enable_stream: boolean;
};

type ReviewSettingsForm = {
  effort: string;
  max_findings_per_mr: string;
  min_confidence: string;
  enable_full_repo_context: boolean;
};

type AgentSettingsForm = {
  max_parallel_agents: string;
  enable_llm_routing: boolean;
  require_rule_coverage: boolean;
  default_max_tool_calls: string;
};

type ToolSettingsForm = {
  static_tool_enabled: Record<string, boolean>;
  analysis_worktree_path: string;
  semgrep_config: string;
  gitleaks_config_path: string;
  checkstyle_config_path: string;
  pmd_rulesets: string;
  kics_queries_path: string;
  enable_mcp: boolean;
  enable_builtin_java_heuristics: boolean;
};

type StaticToolSwitch = {
  key: string;
  availabilityName: string;
  displayName: string;
  category: string;
  requiredFor: string;
};

const STATIC_TOOL_SWITCHES: StaticToolSwitch[] = [
  { key: "tree_sitter_code_graph", availabilityName: "tree-sitter", displayName: "Tree-sitter", category: "Code Graph", requiredFor: "语法图谱、调用关系、影响范围上下文" },
  { key: "semgrep", availabilityName: "semgrep", displayName: "Semgrep", category: "SAST", requiredFor: "Java/Spring 规则、通用安全规则" },
  { key: "gitleaks", availabilityName: "gitleaks", displayName: "Gitleaks", category: "Secret", requiredFor: "密钥泄露扫描" },
  { key: "ruff", availabilityName: "ruff", displayName: "Ruff", category: "Python", requiredFor: "Python 静态检查" },
  { key: "bandit", availabilityName: "bandit", displayName: "Bandit", category: "Python Security", requiredFor: "Python 安全扫描" },
  { key: "eslint", availabilityName: "eslint", displayName: "ESLint", category: "Frontend", requiredFor: "JS/TS 静态检查" },
  { key: "pmd", availabilityName: "pmd", displayName: "PMD", category: "Java Source", requiredFor: "Java 规范、复杂度、安全规则" },
  { key: "checkstyle", availabilityName: "checkstyle", displayName: "Checkstyle", category: "Java Style", requiredFor: "Java 基础规范" },
  { key: "spotbugs", availabilityName: "spotbugs", displayName: "SpotBugs", category: "Java Bytecode", requiredFor: "字节码缺陷、FindSecBugs 安全规则" },
  { key: "dependency-check", availabilityName: "dependency-check", displayName: "Dependency-Check", category: "Dependency", requiredFor: "OWASP 依赖 CVE 扫描" },
  { key: "osv-scanner", availabilityName: "osv-scanner", displayName: "OSV Scanner", category: "Dependency", requiredFor: "OSV 依赖漏洞扫描" },
  { key: "trivy", availabilityName: "trivy", displayName: "Trivy", category: "Container/IaC", requiredFor: "依赖、镜像、配置、密钥扫描" },
  { key: "kics", availabilityName: "kics", displayName: "KICS", category: "IaC", requiredFor: "K8s、Docker、Terraform 配置风险" },
  { key: "openapi-diff", availabilityName: "openapi-diff", displayName: "OpenAPI Diff", category: "API", requiredFor: "OpenAPI 破坏性变更检测" }
];

const DEFAULT_STATIC_TOOL_ENABLED = Object.fromEntries(STATIC_TOOL_SWITCHES.map((tool) => [tool.key, true]));

type QueueSettingsForm = {
  poll_interval_seconds: string;
  max_concurrency: string;
  max_attempts: string;
  heartbeat_timeout_seconds: string;
};

type PublishSettingsForm = {
  require_manual_confirmation: boolean;
  dry_run: boolean;
  allowed_severities: string;
};

type DataSettingsForm = {
  prompt_retention: string;
  diff_max_lines_to_llm: string;
  sensitive_paths: string;
  fallback_on_violation: string;
};

type LlmTestState = {
  status: "idle" | "testing" | "ok" | "failed";
  message: string;
};

type FormActionState = {
  status: "idle" | "saving" | "ok" | "failed";
  message: string;
};

type SuccessNotice = {
  title: string;
  message: string;
  detail?: string;
};

type PublishResultNotice = {
  status: "success" | "failed";
  title: string;
  message: string;
  publishedCount: number;
  requestedCount: number;
  detail?: string;
};

type MarkdownExportResponse = {
  filename: string;
  content_type: string;
  content: string;
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      ...(init?.headers || {})
    }
  });
  const json = await response.json();
  if (!response.ok) {
    throw new Error(json.message || json.error || "API request failed");
  }
  return json as T;
}

function listItems<T>(value: T[] | { items?: T[] } | null | undefined): T[] {
  if (Array.isArray(value)) return value;
  return Array.isArray(value?.items) ? value.items : [];
}

function normalizeMrChangedFiles(value: unknown): MrChangedFile[] {
  const rawItems = Array.isArray(value)
    ? value
    : value && typeof value === "object" && Array.isArray((value as { items?: unknown[] }).items)
      ? (value as { items: unknown[] }).items
      : [];
  return rawItems.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const row = item as Record<string, unknown>;
    const filename = String(row.filename ?? row.new_path ?? row.path ?? "").trim();
    if (!filename) return [];
    return [{
      filename,
      status: row.status ? String(row.status) : undefined,
      additions: Number.isFinite(Number(row.additions)) ? Number(row.additions) : undefined,
      deletions: Number.isFinite(Number(row.deletions)) ? Number(row.deletions) : undefined,
      patch: typeof row.patch === "string" ? row.patch : "",
      previous_filename: row.previous_filename ? String(row.previous_filename) : undefined
    }];
  });
}

function splitCsv(value: string) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function clampLlmTimeout(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(1, Math.min(600, parsed)) : 120;
}

function clampLlmOutputTokens(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(1024, Math.min(12000, parsed)) : 8192;
}

function csvValue(value: unknown) {
  if (Array.isArray(value)) return value.map(String).join(", ");
  return typeof value === "string" ? value : "";
}

function recordValue(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value ? value as Record<string, unknown> : {};
}

function boolValue(value: unknown, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

function staticToolPolicyValue(toolPolicy: Record<string, unknown>, staticRunners: Record<string, unknown>, tool: StaticToolSwitch) {
  const enabledTools = Array.isArray(toolPolicy.enabled_tools) ? toolPolicy.enabled_tools.map(String) : [];
  const disabledTools = Array.isArray(toolPolicy.disabled_tools) ? toolPolicy.disabled_tools.map(String) : [];
  const aliases = new Set([tool.key, tool.availabilityName]);
  const runner = recordValue(staticRunners[tool.key] ?? staticRunners[tool.availabilityName]);
  if (disabledTools.some((item) => aliases.has(item))) return false;
  if (enabledTools.length > 0) return enabledTools.some((item) => aliases.has(item));
  return boolValue(runner.enabled, true);
}

function staticRunnerPayload(toolForm: ToolSettingsForm) {
  const runners: Record<string, Record<string, unknown>> = Object.fromEntries(
    STATIC_TOOL_SWITCHES.map((tool) => [tool.key, { enabled: toolForm.static_tool_enabled[tool.key] !== false }])
  );
  runners.tree_sitter_code_graph = {
    ...runners.tree_sitter_code_graph,
  };
  runners.semgrep = {
    ...runners.semgrep,
    custom_config_paths: splitCsv(toolForm.semgrep_config)
  };
  runners.gitleaks = {
    ...runners.gitleaks,
    extend_config_path: toolForm.gitleaks_config_path.trim()
  };
  runners.checkstyle = {
    ...runners.checkstyle,
    config_path: toolForm.checkstyle_config_path.trim()
  };
  runners.pmd = {
    ...runners.pmd,
    custom_rulesets: splitCsv(toolForm.pmd_rulesets)
  };
  runners.kics = {
    ...runners.kics,
    custom_queries_path: toolForm.kics_queries_path.trim()
  };
  return runners;
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    queued: "等待检视",
    fetching: "读取变更",
    pre_scanning: "工具检查",
    reviewing: "检视中",
    judging: "整理结果",
    running: "检视中",
    waiting_confirmation: "待确认",
    submitted: "已提交",
    no_issue: "无问题",
    paused: "已暂停",
    cancelled: "已停止",
    failed: "失败"
  };
  return map[status] || status;
}

function formatDurationMs(value: unknown) {
  const ms = Number(value || 0);
  if (!Number.isFinite(ms) || ms <= 0) return "0ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)}s`;
}

const ACTIVE_REVIEW_STATUSES = ["fetching", "pre_scanning", "reviewing", "judging", "running"];
const REVIEW_STEPS = [
  { key: "queued", label: "等待开始", description: "任务已提交，正在等待后台处理" },
  { key: "fetching", label: "读取变更", description: "读取 MR 的变更文件和代码内容" },
  { key: "pre_scanning", label: "工具检查", description: "用代码检查工具先找一批确定性问题" },
  { key: "reviewing", label: "AI 专家分析", description: "不同专家按规范分析代码问题" },
  { key: "judging", label: "整理结果", description: "合并重复项，保留证据充分的问题" },
  { key: "done", label: "等待确认", description: "问题已生成，等待你确认后提交到 CodeHub" }
];

function effectiveReviewStatus(detail: Detail) {
  const latestJobStatus = String(detail.jobs?.[0]?.status || "");
  if (ACTIVE_REVIEW_STATUSES.includes(latestJobStatus)) return latestJobStatus;
  return detail.mr.review_status;
}

function reviewStepIndex(status: string) {
  if (status === "queued") return 0;
  if (status === "fetching") return 1;
  if (status === "pre_scanning") return 2;
  if (status === "reviewing" || status === "running") return 3;
  if (status === "judging") return 4;
  return 5;
}

function severityText(severity: string) {
  const map: Record<string, string> = { critical: "严重", high: "高危", medium: "中危", low: "低危" };
  return map[severity] || severity;
}

function severityRank(severity: string) {
  const map: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
  return map[severity] ?? 9;
}

function sortFindingsBySeverity(findings: Finding[]) {
  return [...findings].sort((left, right) => {
    const severityDiff = severityRank(left.severity) - severityRank(right.severity);
    if (severityDiff !== 0) return severityDiff;
    const confidenceDiff = Number(right.confidence || 0) - Number(left.confidence || 0);
    if (confidenceDiff !== 0) return confidenceDiff;
    return (left.file_path || "").localeCompare(right.file_path || "") || Number(left.line_start || 0) - Number(right.line_start || 0);
  });
}

function findingSource(finding: Finding) {
  const observations = parseJsonObjectArray(finding.source_observations_json);
  const provenance = parseJsonObjectArray(finding.tool_provenance_json);
  const toolName = [...observations, ...provenance]
    .map((item) => String(item.tool_name || item.tool || item.source || "").trim())
    .find((value) => value && value !== "tool_observation");
  if (observations.length || provenance.some((item) => item.tool_name || item.source === "tool_observation")) {
    return {
      type: "tool" as const,
      label: "工具检出",
      detail: toolName || agentLabel(finding.agent_id)
    };
  }
  return {
    type: "ai" as const,
    label: "AI 语义检出",
    detail: agentLabel(finding.agent_id)
  };
}

function riskLevel(score: number) {
  if (score >= 70) return "high";
  if (score >= 35) return "medium";
  return "low";
}

function shortTime(value: string) {
  if (!value) return "--";
  const date = new Date(value.replace(" ", "T") + "Z");
  if (Number.isNaN(date.getTime())) return value.slice(11, 16) || value;
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function mrMatchesTimeFilter(value: string, filter: string) {
  if (filter === "all") return true;
  if (!value) return false;
  const date = new Date(value.replace(" ", "T") + "Z");
  if (Number.isNaN(date.getTime())) return false;
  const now = new Date();
  if (filter === "today") return now.toDateString() === date.toDateString();
  const days = filter === "7d" ? 7 : filter === "30d" ? 30 : 0;
  if (!days) return true;
  return now.getTime() - date.getTime() <= days * 24 * 60 * 60 * 1000;
}

function hasNestedVerticalScrollRoom(target: HTMLElement | null, boundary: HTMLElement, deltaY: number) {
  if (!target || deltaY === 0) return false;
  let node: HTMLElement | null = target;
  while (node && node !== boundary) {
    const style = window.getComputedStyle(node);
    const canOverflow = /(auto|scroll|overlay)/.test(style.overflowY);
    if (canOverflow && node.scrollHeight > node.clientHeight + 1) {
      const maxScrollTop = node.scrollHeight - node.clientHeight;
      if ((deltaY > 0 && node.scrollTop < maxScrollTop - 1) || (deltaY < 0 && node.scrollTop > 1)) {
        return true;
      }
    }
    node = node.parentElement;
  }
  return false;
}

function repoNameFromGitUrl(value: string) {
  const normalized = value.trim().replace(/\.git$/i, "");
  const path = normalized.includes(":") && !normalized.includes("://")
    ? normalized.split(":").pop() || normalized
    : normalized.replace(/^https?:\/\/[^/]+\//i, "").replace(/^ssh:\/\/[^/]+\//i, "");
  return path.split("/").filter(Boolean).pop() || normalized;
}

function formatFindingLocation(finding: Pick<Finding, "file_path" | "line_start" | "line_end">) {
  if (!finding.line_start) return finding.file_path;
  if (finding.line_end && finding.line_end !== finding.line_start) {
    return `${finding.file_path}:${finding.line_start}-${finding.line_end}`;
  }
  return `${finding.file_path}:${finding.line_start}`;
}

function formatFindingLineRange(finding: Pick<Finding, "line_start" | "line_end">) {
  if (!finding.line_start) return "行号 --";
  if (finding.line_end && finding.line_end !== finding.line_start) {
    return `L${finding.line_start}-L${finding.line_end}`;
  }
  return `L${finding.line_start}`;
}

function shortPath(value: string) {
  if (!value || value === "--") return "--";
  const parts = value.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.length > 3 ? parts.slice(-3).join("/") : value;
}

function providerLabel(provider: string) {
  if (provider === "github") return "GitHub";
  if (provider === "codehub") return "CodeHub";
  return provider || "--";
}

function textCodeLines(value: string, startLine = 1): ParsedDiffLine[] {
  const lines = String(value || "").split(/\r?\n/);
  return lines.map((content, index) => ({
    kind: "context",
    oldLine: startLine + index,
    newLine: startLine + index,
    content
  }));
}

function sourceCodeWindow(source: string, startLine: number, endLine: number): ParsedDiffLine[] {
  const allLines = source.split(/\r?\n/);
  const safeStart = Math.max(1, startLine - 4);
  const safeEnd = Math.min(allLines.length, Math.max(endLine, startLine) + 4);
  return allLines.slice(safeStart - 1, safeEnd).map((content, index) => ({
    kind: "context",
    oldLine: safeStart + index,
    newLine: safeStart + index,
    content
  }));
}

function diffCodeWindow(patch: string, startLine: number, endLine: number): ParsedDiffLine[] {
  const parsed = parseUnifiedPatch(patch);
  if (!parsed.length) return [];
  const targetStart = Math.max(1, startLine || 1);
  const targetEnd = Math.max(targetStart, endLine || targetStart);
  const matchIndex = parsed.findIndex((line) => {
    const newLine = typeof line.newLine === "number" ? line.newLine : 0;
    const oldLine = typeof line.oldLine === "number" ? line.oldLine : 0;
    return (newLine >= targetStart && newLine <= targetEnd) || (oldLine >= targetStart && oldLine <= targetEnd);
  });
  if (matchIndex < 0) return [];
  let safeStart = Math.max(0, matchIndex - 5);
  while (safeStart > 0 && parsed[safeStart].kind !== "meta" && matchIndex - safeStart < 12) {
    safeStart -= 1;
  }
  const safeEnd = Math.min(parsed.length, matchIndex + 8);
  return parsed.slice(safeStart, safeEnd);
}

function parseUnifiedPatch(patch: string): ParsedDiffLine[] {
  const result: ParsedDiffLine[] = [];
  let oldLine = 0;
  let newLine = 0;
  for (const raw of String(patch || "").split(/\r?\n/)) {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/.exec(raw);
    if (hunk) {
      oldLine = Number(hunk[1]);
      newLine = Number(hunk[2]);
      result.push({ kind: "meta", oldLine: null, newLine: null, content: raw });
      continue;
    }
    if (raw.startsWith("+") && !raw.startsWith("+++")) {
      result.push({ kind: "add", oldLine: null, newLine: newLine++, content: raw.slice(1) });
      continue;
    }
    if (raw.startsWith("-") && !raw.startsWith("---")) {
      result.push({ kind: "del", oldLine: oldLine++, newLine: null, content: raw.slice(1) });
      continue;
    }
    if (!raw.startsWith("\\ No newline")) {
      result.push({ kind: "context", oldLine: oldLine || null, newLine: newLine || null, content: raw.startsWith(" ") ? raw.slice(1) : raw });
      if (oldLine) oldLine += 1;
      if (newLine) newLine += 1;
    }
  }
  return result.length ? result : [{ kind: "meta", oldLine: null, newLine: null, content: "该文件没有可展示的 patch。" }];
}

function buildFileTree(files: MrChangedFile[]) {
  const sortedFiles = [...files].sort((left, right) => left.filename.localeCompare(right.filename));
  const entries: Array<{
    key: string;
    path: string;
    name: string;
    depth: number;
    kind: "directory" | "file";
    status?: string;
    file?: MrChangedFile;
  }> = [];
  const seenDirectories = new Set<string>();
  for (const file of sortedFiles) {
    const parts = file.filename.split("/").filter(Boolean);
    const fileName = parts[parts.length - 1] || file.filename;
    let currentPath = "";
    parts.slice(0, -1).forEach((part, index) => {
      currentPath = currentPath ? `${currentPath}/${part}` : part;
      if (seenDirectories.has(currentPath)) return;
      seenDirectories.add(currentPath);
      entries.push({
        key: `dir:${currentPath}`,
        path: currentPath,
        name: part,
        depth: index,
        kind: "directory"
      });
    });
    entries.push({
      key: `file:${file.filename}`,
      path: file.filename,
      name: fileName,
      depth: Math.max(0, parts.length - 1),
      kind: "file",
      status: file.status || "modified",
      file
    });
  }
  return entries;
}

function basename(path: string) {
  const parts = String(path || "").split("/").filter(Boolean);
  return parts[parts.length - 1] || path || "--";
}

function App() {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [mrs, setMrs] = useState<MergeRequest[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [activeMrId, setActiveMrId] = useState<string | null>(null);
  const activeMrIdRef = useRef<string | null>(null);
  const [mrPreview, setMrPreview] = useState<Detail | null>(null);
  const [mrPreviewFiles, setMrPreviewFiles] = useState<MrChangedFile[]>([]);
  const [mrPreviewLoading, setMrPreviewLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");
  const [repoFilter, setRepoFilter] = useState("all");
  const [authorFilter, setAuthorFilter] = useState("all");
  const [timeFilter, setTimeFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pendingMrActions, setPendingMrActions] = useState<Record<string, MrActionState>>({});
  const [repoInput, setRepoInput] = useState("");
  const [message, setMessage] = useState("CodeHub 已同步 · 2 分钟前");
  const [publishNotice, setPublishNotice] = useState<PublishResultNotice | null>(null);
  const [activeView, setActiveView] = useState<ViewKey>("mr");
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProjectId, setActiveProjectId] = useState(DEFAULT_PROJECT_ID);
  const [projectChosen, setProjectChosen] = useState(false);
  const workspaceScrollRef = useRef<HTMLDivElement | null>(null);

  async function loadAll(nextActiveId?: string | null) {
    const [repoData, mrData] = await Promise.all([
      api<Repo[]>(`/api/projects/${activeProjectId}/repositories`),
      api<{ items: MergeRequest[] }>(`/api/mr-review/projects/${activeProjectId}/merge-requests`)
    ]);
    setRepos(repoData);
    setMrs(mrData.items);
    const requestedId = nextActiveId ?? activeMrIdRef.current ?? activeMrId ?? null;
    const selectedId = requestedId && mrData.items.some((mr) => mr.id === requestedId)
      ? requestedId
      : mrData.items[0]?.id ?? null;
    activeMrIdRef.current = selectedId;
    setActiveMrId(selectedId);
    if (selectedId) {
      setDetail(await api<Detail>(`/api/mr-review/merge-requests/${selectedId}`));
    } else {
      setDetail(null);
    }
  }

  useEffect(() => {
    async function bootstrapSession() {
      try {
        if (authToken) {
          const session = await api<{ authenticated: boolean; user: User }>("/api/auth/session");
          if (!session.authenticated) setApiToken(null);
        }
        if (!authToken) {
          const login = await api<{ token: string; user: User }>("/api/auth/login", {
            method: "POST",
            body: JSON.stringify({ username: "local-admin" })
          });
          setApiToken(login.token);
          setUser(login.user);
        }
        const me = await api<{ user: User; projects: Project[] }>("/api/me");
        setUser(me.user);
        setProjects(me.projects);
        if (me.projects[0]?.id) setActiveProjectId(me.projects[0].id);
        setReady(true);
      } catch (error) {
        setMessage((error as Error).message);
      }
    }
    bootstrapSession();
  }, []);

  useEffect(() => {
    if (!ready || !projectChosen) return;
    loadAll(null).catch((error) => setMessage(error.message));
    const timer = window.setInterval(() => loadAll().catch(() => undefined), 8000);
    return () => window.clearInterval(timer);
  }, [ready, projectChosen, activeProjectId]);

  async function sync() {
    setSyncing(true);
    setMessage("正在同步项目已绑定代码仓的 MR...");
    try {
      const result = await api<{
        repositories: number;
        merge_requests: number;
        jobs_created: number;
        errors: string[];
        repository_results?: Array<{ name: string; merge_requests: number; jobs_created: number; error?: string }>;
      }>(
        `/api/mr-review/projects/${activeProjectId}/sync`,
        { method: "POST", body: "{}" }
      );
      await loadAll(activeMrId);
      const repoSummary = (result.repository_results || [])
        .slice(0, 4)
        .map((repo) => `${repo.name}:${repo.merge_requests}${repo.error ? "!" : ""}`)
        .join("，");
      const suffix = repoSummary ? ` · ${repoSummary}${(result.repository_results?.length || 0) > 4 ? "…" : ""}` : "";
      setMessage(`已同步 ${result.repositories} 个代码仓 · ${result.merge_requests} 个 MR · 新增 ${result.jobs_created} 个任务${suffix}`);
      if (result.errors.length) setMessage(`同步完成，但有错误：${result.errors.join("; ")}`);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setSyncing(false);
    }
  }

  async function bindRepo() {
    const gitUrl = repoInput.trim();
    if (!gitUrl.includes("/") || !gitUrl.includes(".git")) {
      setMessage("请输入 Git 仓库链接，例如 https://codehub.example.com/team/repo.git");
      return;
    }
    setBusy(true);
    try {
      await api(`/api/projects/${activeProjectId}/repositories`, {
        method: "POST",
        body: JSON.stringify({
          provider: "github",
          git_url: gitUrl,
          name: repoNameFromGitUrl(gitUrl),
          default_branch: "main"
        })
      });
      setRepoInput("");
      await loadAll(activeMrId);
      setMessage(`已绑定仓库 ${gitUrl}`);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function optimisticMrStatus(mrId: string, status: string) {
    const updatedAt = new Date().toISOString();
    setMrs((previous) => previous.map((mr) => (
      mr.id === mrId ? { ...mr, review_status: status, updated_at: updatedAt } : mr
    )));
    setDetail((previous) => (
      previous?.mr.id === mrId
        ? { ...previous, mr: { ...previous.mr, review_status: status, updated_at: updatedAt } }
        : previous
    ));
  }

  function beginMrAction(mrId: string, action: MrActionState, status: string) {
    setPendingMrActions((previous) => ({ ...previous, [mrId]: action }));
    optimisticMrStatus(mrId, status);
  }

  function endMrAction(mrId: string) {
    setPendingMrActions((previous) => {
      const next = { ...previous };
      delete next[mrId];
      return next;
    });
  }

  async function openMr(id: string, showPreview = false) {
    activeMrIdRef.current = id;
    setActiveMrId(id);
    const nextDetail = await api<Detail>(`/api/mr-review/merge-requests/${id}`);
    setDetail(nextDetail);
    if (showPreview) {
      setMrPreview(nextDetail);
      setMrPreviewFiles([]);
      setMrPreviewLoading(true);
      try {
        const files = await api<unknown>(`/api/vcs/${activeProjectId}/merge-requests/${id}/files`);
        setMrPreviewFiles(normalizeMrChangedFiles(files));
      } catch (error) {
        setMessage(`MR diff 加载失败：${(error as Error).message}`);
        setMrPreviewFiles([]);
      } finally {
        setMrPreviewLoading(false);
      }
    }
  }

  async function rerunReview(mrId = detail?.mr.id) {
    if (!mrId) return;
    beginMrAction(mrId, "rerun", "reviewing");
    setBusy(true);
    try {
      await api(`/api/mr-review/merge-requests/${mrId}/review-jobs`, {
        method: "POST",
        body: JSON.stringify({ effort_level: "standard", reason: "manual_retry" })
      });
      await loadAll(mrId);
      setMessage("已提交重新检视请求，系统正在处理");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      endMrAction(mrId);
      setBusy(false);
    }
  }

  async function startReview(mrId: string) {
    beginMrAction(mrId, "start", "reviewing");
    setBusy(true);
    try {
      await api(`/api/mr-review/merge-requests/${mrId}/review-jobs`, {
        method: "POST",
        body: JSON.stringify({ effort_level: "standard", reason: "manual_start" })
      });
      await loadAll(mrId);
      setMessage("已提交开始请求，系统正在处理");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      endMrAction(mrId);
      setBusy(false);
    }
  }

  async function pauseReview(mrId: string) {
    beginMrAction(mrId, "pause", "paused");
    setBusy(true);
    try {
      await api(`/api/mr-review/merge-requests/${mrId}/pause`, { method: "POST", body: "{}" });
      await loadAll(mrId);
      setMessage("已暂停该 MR 的检视任务");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      endMrAction(mrId);
      setBusy(false);
    }
  }

  async function stopReview(mrId: string) {
    beginMrAction(mrId, "stop", "cancelled");
    setBusy(true);
    try {
      await api(`/api/mr-review/merge-requests/${mrId}/stop`, { method: "POST", body: "{}" });
      await loadAll(mrId);
      setMessage("已停止该 MR 的检视任务");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      endMrAction(mrId);
      setBusy(false);
    }
  }

  async function deleteMr(mr: MergeRequest) {
    if (!window.confirm(`删除本地 MR !${mr.number}？删除后可通过重新同步再次拉取。`)) return;
    setBusy(true);
    try {
      const result = await api<{ deleted_jobs: number; deleted_runs: number; deleted_findings: number }>(
        `/api/mr-review/merge-requests/${mr.id}`,
        { method: "DELETE" }
      );
      if (activeMrIdRef.current === mr.id) {
        activeMrIdRef.current = null;
        setActiveMrId(null);
        setDetail(null);
      }
      await loadAll(activeMrIdRef.current);
      setMessage(`已删除 MR !${mr.number}，清理 ${result.deleted_jobs} 个任务、${result.deleted_runs} 次运行、${result.deleted_findings} 条 finding；重新同步可再次拉取`);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function toggleFinding(finding: Finding) {
    await api(`/api/mr-review/review-findings/${finding.id}`, {
      method: "PATCH",
      body: JSON.stringify({ selected: !finding.selected })
    });
    if (detail) await openMr(detail.mr.id);
  }

  async function setAllFindingsSelected(selected: boolean) {
    if (!detail) return;
    const targets = detail.findings.filter((finding) => Boolean(finding.selected) !== selected);
    if (!targets.length) return;
    setBusy(true);
    try {
      await Promise.all(targets.map((finding) =>
        api(`/api/mr-review/review-findings/${finding.id}`, {
          method: "PATCH",
          body: JSON.stringify({ selected })
        })
      ));
      await loadAll(detail.mr.id);
      setMessage(selected ? `已全选 ${detail.findings.length} 条检视意见` : "已取消全选检视意见");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function markFalsePositive(finding: Finding) {
    await api(`/api/mr-review/review-findings/${finding.id}/feedback`, {
      method: "POST",
      body: JSON.stringify({ feedback_type: "false_positive" })
    });
    if (detail) await openMr(detail.mr.id);
  }

  async function markSelectedFalsePositive() {
    if (!detail) return;
    const selected = detail.findings.filter((finding) => finding.selected);
    if (!selected.length) {
      setMessage("没有选中的 finding");
      return;
    }
    setBusy(true);
    try {
      for (const finding of selected) {
        await api(`/api/mr-review/review-findings/${finding.id}/feedback`, {
          method: "POST",
          body: JSON.stringify({ feedback_type: "false_positive", scope: "merge_request" })
        });
      }
      await loadAll(detail.mr.id);
      setMessage(`已标记 ${selected.length} 条误报`);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function publish(dryRun = false) {
    if (!detail) return;
    const findingIds = detail.findings.filter((finding) => finding.selected).map((finding) => finding.id);
    const requestedCount = findingIds.length;
    if (!findingIds.length) {
      setMessage("没有选中的 finding");
      return;
    }
    setBusy(true);
    try {
      const result = await api<{ published_count: number; dry_run: boolean }>(`/api/mr-review/merge-requests/${detail.mr.id}/publish`, {
        method: "POST",
        body: JSON.stringify({ finding_ids: findingIds, dry_run: dryRun })
      });
      await loadAll(detail.mr.id);
      const publishedCount = Number(result.published_count || 0);
      const actionLabel = result.dry_run ? "生成 dry-run 发布记录" : "提交检视意见";
      const title = result.dry_run
        ? "发布预览已生成"
        : publishedCount === requestedCount
          ? "检视意见提交成功"
          : "检视意见部分提交成功";
      const successMessage = `成功${actionLabel} ${publishedCount} / ${requestedCount} 条。`;
      setMessage(result.dry_run ? `已生成 ${publishedCount} 条 dry-run 发布记录` : `已发布 ${publishedCount} 条意见`);
      setPublishNotice({
        status: "success",
        title,
        message: successMessage,
        publishedCount,
        requestedCount,
        detail: result.dry_run ? "当前为 dry-run，仅生成发布记录，不会提交到代码平台。" : "已完成代码平台提交请求。"
      });
    } catch (error) {
      const errorMessage = (error as Error).message;
      setMessage(errorMessage);
      setPublishNotice({
        status: "failed",
        title: "检视意见提交失败",
        message: `成功提交 0 / ${requestedCount} 条。`,
        publishedCount: 0,
        requestedCount,
        detail: errorMessage
      });
    } finally {
      setBusy(false);
    }
  }

  async function exportMarkdown() {
    if (!detail) return;
    setBusy(true);
    try {
      const result = await api<MarkdownExportResponse>(`/api/mr-review/merge-requests/${detail.mr.id}/export.md`);
      const blob = new Blob([result.content], { type: result.content_type || "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const filename = result.filename || `jolt-mr-${detail.mr.number}-review.md`;
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setMessage(`已导出 ${filename}`);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const stats = useMemo(() => {
    const queued = mrs.filter((mr) => mr.review_status === "queued").length;
    const reviewing = mrs.filter((mr) => ["fetching", "pre_scanning", "reviewing", "judging", "running"].includes(mr.review_status)).length;
    const waiting = mrs.filter((mr) => mr.review_status === "waiting_confirmation").length;
    const highRisk = mrs.filter((mr) => mr.risk_score >= 70).length;
    const submitted = mrs.filter((mr) => mr.review_status === "submitted").length;
    return { all: mrs.length, queued, reviewing, waiting, highRisk, submitted };
  }, [mrs]);

  const filteredMrs = useMemo(() => {
    return mrs.filter((mr) => {
      const statusOk =
        statusFilter === "all" ||
        (statusFilter === "reviewing" && ["fetching", "pre_scanning", "reviewing", "judging", "running"].includes(mr.review_status)) ||
        (statusFilter === "high_risk" && mr.risk_score >= 70) ||
        mr.review_status === statusFilter;
      const repoOk = repoFilter === "all" || mr.repository_id === repoFilter || mr.repository_name === repoFilter;
      const authorOk = authorFilter === "all" || mr.author === authorFilter;
      const timeOk = mrMatchesTimeFilter(mr.updated_at, timeFilter);
      const text = `${mr.title} ${mr.repository_name} ${mr.author} ${mr.number}`.toLowerCase();
      return statusOk && repoOk && authorOk && timeOk && text.includes(query.toLowerCase());
    });
  }, [authorFilter, mrs, query, repoFilter, statusFilter, timeFilter]);

  const activeProject = projects.find((project) => project.id === activeProjectId) ?? projects[0];
  const activeProjectRole = String(activeProject?.role || "");

  async function logout() {
    await api("/api/auth/logout", { method: "POST", body: "{}" }).catch(() => undefined);
    setApiToken(null);
    setUser(null);
    setReady(false);
    window.location.reload();
  }

  function handleWorkspaceWheel(event: React.WheelEvent<HTMLDivElement>) {
    const node = event.currentTarget;
    if (node.scrollWidth <= node.clientWidth) return;
    const target = event.target instanceof HTMLElement ? event.target : null;
    if (hasNestedVerticalScrollRoom(target, node, event.deltaY)) return;

    const horizontalDelta = Math.abs(event.deltaX) > 0 ? event.deltaX : 0;
    const verticalAsHorizontal = horizontalDelta === 0 ? event.deltaY : 0;
    const delta = horizontalDelta || verticalAsHorizontal;
    if (!delta) return;
    const before = node.scrollLeft;
    node.scrollLeft += delta;
    if (node.scrollLeft !== before) event.preventDefault();
  }

  function handleWorkspaceKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const node = workspaceScrollRef.current;
    if (!node || node.scrollWidth <= node.clientWidth) return;
    if (event.target instanceof HTMLElement) {
      const tagName = event.target.tagName.toLowerCase();
      if (["input", "textarea", "select", "button"].includes(tagName)) return;
    }
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    node.scrollBy({ left: event.key === "ArrowRight" ? 240 : -240, behavior: "smooth" });
    event.preventDefault();
  }

  async function refreshProjects() {
    const me = await api<{ user: User; projects: Project[] }>("/api/me");
    setUser(me.user);
    setProjects(me.projects);
    if (!me.projects.some((project) => project.id === activeProjectId) && me.projects[0]?.id) {
      setActiveProjectId(me.projects[0].id);
    }
  }

  async function enterProject(projectId: string) {
    setActiveProjectId(projectId);
    setProjectChosen(true);
    activeMrIdRef.current = null;
    setActiveMrId(null);
    setDetail(null);
  }

  if (ready && !projectChosen) {
    return (
      <ProjectSelectionPage
        user={user}
        projects={projects}
        refreshProjects={refreshProjects}
        enterProject={enterProject}
        logout={logout}
      />
    );
  }

  return (
    <div className="app-shell">
      <Sidebar
        projects={projects}
        activeProjectId={activeProjectId}
        setActiveProjectId={setActiveProjectId}
        repos={repos}
        repoInput={repoInput}
        setRepoInput={setRepoInput}
        bindRepo={bindRepo}
        busy={busy}
        activeView={activeView}
        setActiveView={setActiveView}
        backToProjects={() => setProjectChosen(false)}
      />
      <main className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            <strong>{activeProject?.name || "默认项目"}</strong>
            <span>/</span>
            <strong>{viewTitle(activeView)}</strong>
          </div>
          <div className="global-search">
            <Search size={18} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 MR、仓库、作者" />
            <kbd>/</kbd>
          </div>
          <div className="top-actions">
            <span className="sync-state">
              <CheckCircle2 size={18} />
              {message}
            </span>
            <button className="user-chip" type="button" onClick={logout}>
              <UserRound size={17} />
              {user?.display_name || user?.username || "local-admin"}
            </button>
            <button className="square-button" type="button" onClick={sync} aria-label="刷新" disabled={syncing}>
              {syncing ? <Loader2 className="spin" size={19} /> : <RefreshCw size={19} />}
              <span className="tooltip">刷新</span>
            </button>
          </div>
        </header>

        {activeView === "mr" ? (
          <div
            ref={workspaceScrollRef}
            className="workspace-scroll"
            tabIndex={0}
            aria-label="MR 工作台横向滚动区域"
            onWheel={handleWorkspaceWheel}
            onKeyDown={handleWorkspaceKeyDown}
          >
            <section className="content-grid">
              <MrQueue
                items={filteredMrs}
                activeMrId={activeMrId}
                openMr={(id) => openMr(id)}
                previewMr={(id) => openMr(id, true)}
                statusFilter={statusFilter}
                setStatusFilter={setStatusFilter}
                repoFilter={repoFilter}
                setRepoFilter={setRepoFilter}
                authorFilter={authorFilter}
                setAuthorFilter={setAuthorFilter}
                timeFilter={timeFilter}
                setTimeFilter={setTimeFilter}
                repos={repos}
                authors={Array.from(new Set(mrs.map((mr) => mr.author).filter(Boolean))).sort()}
                stats={stats}
                sync={sync}
                syncing={syncing}
                busy={busy}
                pendingMrActions={pendingMrActions}
                startReview={startReview}
                pauseReview={pauseReview}
                stopReview={stopReview}
                rerunReview={rerunReview}
                deleteMr={deleteMr}
              />
              <DetailPanel
                detail={detail}
                busy={busy}
                onRerun={rerunReview}
                onToggleFinding={toggleFinding}
                onToggleAllFindings={setAllFindingsSelected}
                onFalsePositive={markFalsePositive}
                onBulkFalsePositive={markSelectedFalsePositive}
                onExportMarkdown={exportMarkdown}
                onPublish={() => publish(false)}
                projectId={activeProjectId}
              />
            </section>
          </div>
        ) : (
          <ConfigWorkspace
            view={activeView}
            projectId={activeProjectId}
            repos={repos}
            reload={loadAll}
            setMessage={setMessage}
            canEdit={["project_admin", "system_admin"].includes(activeProjectRole)}
          />
        )}
        {mrPreview && (
          <MrPreviewModal
            detail={mrPreview}
            files={mrPreviewFiles}
            loading={mrPreviewLoading}
            onClose={() => {
              setMrPreview(null);
              setMrPreviewFiles([]);
            }}
          />
        )}
        {publishNotice && <PublishResultModal notice={publishNotice} onClose={() => setPublishNotice(null)} />}
      </main>
    </div>
  );
}

function PublishResultModal({ notice, onClose }: { notice: PublishResultNotice; onClose: () => void }) {
  const success = notice.status === "success";
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={notice.title} onClick={onClose}>
      <section className={`publish-result-modal ${notice.status}`} onClick={(event) => event.stopPropagation()}>
        <div className="publish-result-icon">
          {success ? <Check /> : <Circle />}
        </div>
        <div className="publish-result-content">
          <strong>{notice.title}</strong>
          <p>{notice.message}</p>
          <div className="publish-result-counts" aria-label="发布结果统计">
            <span><b>{notice.publishedCount}</b> 成功</span>
            <span><b>{notice.requestedCount}</b> 选中</span>
          </div>
          {notice.detail && <span className="publish-result-detail">{notice.detail}</span>}
          <button type="button" onClick={onClose}>知道了</button>
        </div>
      </section>
    </div>
  );
}

function viewTitle(view: ViewKey) {
  const map: Record<ViewKey, string> = {
    mr: "MR 队列",
    full: "全量检视",
    issues: "问题总览",
    rules: "规则库",
    agents: "专家与规则",
    repos: "代码仓库",
    policy: "检视策略",
    users: "用户权限",
    tools: "工具链",
    queue: "队列运维",
    settings: "系统设置"
  };
  return map[view];
}

function Sidebar({
  projects,
  activeProjectId,
  setActiveProjectId,
  repos,
  repoInput,
  setRepoInput,
  bindRepo,
  busy,
  activeView,
  setActiveView,
  backToProjects
}: {
  projects: Project[];
  activeProjectId: string;
  setActiveProjectId: (value: string) => void;
  repos: Repo[];
  repoInput: string;
  setRepoInput: (value: string) => void;
  bindRepo: () => void;
  busy: boolean;
  activeView: ViewKey;
  setActiveView: (view: ViewKey) => void;
  backToProjects: () => void;
}) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <Zap className="brand-icon" size={30} fill="currentColor" />
        <strong>Jolt CodeReview</strong>
      </div>
      <label className="project-select">
        <select value={activeProjectId} onChange={(event) => setActiveProjectId(event.target.value)}>
          {projects.map((project) => (
            <option key={project.id} value={project.id}>{project.name}</option>
          ))}
          {!projects.length && <option value={activeProjectId}>默认项目</option>}
        </select>
        <ChevronDown size={18} />
      </label>
      <nav className="nav">
        <NavItem icon={<GitBranch />} label="MR 队列" active={activeView === "mr"} onClick={() => setActiveView("mr")} />
        <NavItem icon={<Bot />} label="专家与规则" active={activeView === "agents"} onClick={() => setActiveView("agents")} />
        <NavItem icon={<Clock3 />} label="队列运维" active={activeView === "queue"} onClick={() => setActiveView("queue")} />
        <NavItem icon={<LockKeyhole />} label="用户权限" active={activeView === "users"} onClick={() => setActiveView("users")} />
        <NavItem icon={<Settings />} label="系统设置" active={activeView === "settings"} onClick={() => setActiveView("settings")} />
      </nav>
      <button className="collapse-button" type="button" onClick={backToProjects}>
        <ChevronLeft size={16} />
        返回项目
      </button>
    </aside>
  );
}

function NavItem({ icon, label, active, muted, onClick }: { icon: React.ReactElement<{ size?: number }>; label: string; active?: boolean; muted?: boolean; onClick?: () => void }) {
  return (
    <button type="button" className={`nav-item ${active ? "active" : ""} ${muted ? "muted" : ""}`} onClick={onClick}>
      {React.cloneElement(icon, { size: 21 })}
      <span>{label}</span>
    </button>
  );
}

function ProjectSelectionPage({
  user,
  projects,
  refreshProjects,
  enterProject,
  logout
}: {
  user: User | null;
  projects: Project[];
  refreshProjects: () => Promise<void>;
  enterProject: (projectId: string) => void;
  logout: () => void;
}) {
  return (
    <main className="project-home">
      <header className="project-home-top">
        <div className="brand">
          <Zap className="brand-icon" size={30} fill="currentColor" />
          <strong>Jolt CodeReview</strong>
        </div>
        <button className="user-chip" type="button" onClick={logout}>
          <UserRound size={17} />
          {user?.display_name || user?.username || "local-admin"}
        </button>
      </header>
      <section className="project-home-heading">
        <h1>选择项目</h1>
        <p>项目隔离仓库、规则、专家 Agent、模型配置和检视队列。进入项目后只展示该项目的 MR 工作台。</p>
      </section>
      <section className="project-card-grid">
        {projects.map((project) => (
          <ProjectCard key={project.id} project={project} refreshProjects={refreshProjects} enterProject={enterProject} />
        ))}
        {!projects.length && <div className="config-table-empty">暂无可访问项目</div>}
      </section>
    </main>
  );
}

function ProjectCard({
  project,
  refreshProjects,
  enterProject
}: {
  project: Project;
  refreshProjects: () => Promise<void>;
  enterProject: (projectId: string) => void;
}) {
  const canEdit = ["project_admin", "system_admin"].includes(String(project.role || ""));
  const [repos, setRepos] = useState<Repo[]>([]);
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description || "");
  const [provider, setProvider] = useState("github");
  const [repoId, setRepoId] = useState("");
  const [repoName, setRepoName] = useState("");
  const [maintenanceOpen, setMaintenanceOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  async function loadRepos() {
    setRepos(await api<Repo[]>(`/api/projects/${project.id}/repositories`));
  }

  useEffect(() => {
    loadRepos().catch(() => undefined);
  }, [project.id]);

  useEffect(() => {
    setName(project.name);
    setDescription(project.description || "");
  }, [project.id, project.name, project.description]);

  async function saveProject() {
    setBusy(true);
    try {
      await api(`/api/projects/${project.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name, description })
      });
      await refreshProjects();
    } finally {
      setBusy(false);
    }
  }

  async function bindProjectRepo() {
    const gitUrl = repoId.trim();
    if (!gitUrl) return;
    setBusy(true);
    try {
      await api(`/api/projects/${project.id}/repositories`, {
        method: "POST",
        body: JSON.stringify({
          provider,
          git_url: gitUrl,
          name: repoName.trim() || repoNameFromGitUrl(gitUrl),
          default_branch: "main"
        })
      });
      setRepoId("");
      setRepoName("");
      await loadRepos();
    } finally {
      setBusy(false);
    }
  }

  async function deleteProjectRepo(repo: Repo) {
    if (!window.confirm(`删除已绑定代码仓 ${repo.name}？`)) return;
    setBusy(true);
    try {
      await api(`/api/projects/${project.id}/repositories/${repo.id}`, { method: "DELETE" });
      await loadRepos();
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="project-card">
      <div className="project-card-head">
        <div>
          <strong>{project.name}</strong>
          <span>{project.description || "未填写项目描述"}</span>
        </div>
        <div className="project-card-tools">
          <span className="state-pill on">{project.role || "observer"}</span>
          <button
            className="project-settings-button"
            type="button"
            onClick={() => setMaintenanceOpen(true)}
            aria-label={`维护项目 ${project.name}`}
            title="维护项目"
          >
            <Settings size={17} />
          </button>
        </div>
      </div>
      <div className="project-card-metrics">
        <span>仓库 {repos.length}</span>
        <span>GitHub {repos.filter((repo) => repo.provider === "github").length}</span>
        <span>CodeHub {repos.filter((repo) => repo.provider === "codehub").length}</span>
      </div>
      <div className="project-card-actions">
        <button type="button" onClick={() => enterProject(project.id)}>进入工作台</button>
      </div>
      {maintenanceOpen && (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-labelledby={`project-maintenance-${project.id}`}
          onClick={() => setMaintenanceOpen(false)}
        >
          <section className="project-maintenance-modal" onClick={(event) => event.stopPropagation()}>
            <header>
              <div>
                <span>项目维护</span>
                <strong id={`project-maintenance-${project.id}`}>{project.name}</strong>
                <p>维护项目基础信息和关联代码仓。进入工作台后会自动同步这些仓库的待检视 MR。</p>
              </div>
            </header>
            <div className="project-maintenance">
              <section className="project-maintenance-section">
                <h3>基础信息</h3>
                <label>
                  <span>项目名称</span>
                  <input value={name} onChange={(event) => setName(event.target.value)} disabled={!canEdit} />
                </label>
                <label>
                  <span>项目描述</span>
                  <textarea value={description} onChange={(event) => setDescription(event.target.value)} disabled={!canEdit} />
                </label>
                <button type="button" onClick={saveProject} disabled={!canEdit || busy}>保存项目</button>
              </section>
              <section className="project-maintenance-section">
                <h3>关联代码仓</h3>
                <div className="project-repo-editor">
                  <select value={provider} onChange={(event) => setProvider(event.target.value)} disabled={!canEdit}>
                    <option value="github">GitHub</option>
                    <option value="codehub">CodeHub</option>
                  </select>
                  <input value={repoId} onChange={(event) => setRepoId(event.target.value)} placeholder="Git 仓库链接，例如 https://git.example.com/team/repo.git" disabled={!canEdit} />
                  <input value={repoName} onChange={(event) => setRepoName(event.target.value)} placeholder="仓库显示名" disabled={!canEdit} />
                  <button type="button" onClick={bindProjectRepo} disabled={!canEdit || busy}>绑定仓库</button>
                </div>
                <div className="project-repo-list">
                  {repos.map((repo) => (
                    <p key={repo.id}>
                      <span className="repo-provider">{providerLabel(repo.provider)}</span>
                      <strong>{repo.name}</strong>
                      <em>{repo.external_repo_id}</em>
                      <button
                        className="repo-delete-button"
                        type="button"
                        onClick={() => deleteProjectRepo(repo)}
                        disabled={!canEdit || busy}
                        aria-label={`删除代码仓 ${repo.name}`}
                        title="删除代码仓"
                      >
                        <Trash2 size={15} />
                      </button>
                    </p>
                  ))}
                  {!repos.length && <div className="config-table-empty">暂无绑定仓库</div>}
                </div>
              </section>
            </div>
          </section>
        </div>
      )}
    </article>
  );
}

function ConfigWorkspace({
  view,
  projectId,
  repos,
  reload,
  setMessage,
  canEdit
}: {
  view: ViewKey;
  projectId: string;
  repos: Repo[];
  reload: () => Promise<void>;
  setMessage: (value: string) => void;
  canEdit: boolean;
}) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [quality, setQuality] = useState<Record<string, unknown> | null>(null);
  const [toolchain, setToolchain] = useState<Record<string, unknown> | null>(null);
  const [staticToolAvailability, setStaticToolAvailability] = useState<StaticToolAvailability | null>(null);
  const [queueSummary, setQueueSummary] = useState<Record<string, unknown> | null>(null);
  const [deadLetters, setDeadLetters] = useState<Record<string, unknown>[]>([]);
  const [effectiveConfig, setEffectiveConfig] = useState<Record<string, unknown> | null>(null);
  const [configLoading, setConfigLoading] = useState(false);
  const [configLoadError, setConfigLoadError] = useState("");
  const [settingsLoadedKey, setSettingsLoadedKey] = useState("");
  const [llmForm, setLlmForm] = useState<LlmSettingsForm>({
    default_provider: "dashscope-openai-compatible",
    default_base_url: "https://ark.cn-beijing.volces.com/api/coding/v3",
    default_model: "MiniMax-M2.7",
    default_api_key_env: "",
    default_api_key: "",
    request_timeout_seconds: "120",
    max_output_tokens: "8192",
    enable_stream: true
  });
  const [llmStoredApiKey, setLlmStoredApiKey] = useState("");
  const [reviewForm, setReviewForm] = useState<ReviewSettingsForm>({ effort: "standard", max_findings_per_mr: "40", min_confidence: "0.75", enable_full_repo_context: true });
  const [agentForm, setAgentForm] = useState<AgentSettingsForm>({ max_parallel_agents: "3", enable_llm_routing: true, require_rule_coverage: true, default_max_tool_calls: "12" });
  const [toolForm, setToolForm] = useState<ToolSettingsForm>({
    static_tool_enabled: DEFAULT_STATIC_TOOL_ENABLED,
    analysis_worktree_path: "",
    semgrep_config: "",
    gitleaks_config_path: "",
    checkstyle_config_path: "",
    pmd_rulesets: "",
    kics_queries_path: "",
    enable_mcp: false,
    enable_builtin_java_heuristics: false
  });
  const [queueForm, setQueueForm] = useState<QueueSettingsForm>({ poll_interval_seconds: "300", max_concurrency: "2", max_attempts: "3", heartbeat_timeout_seconds: "600" });
  const [publishForm, setPublishForm] = useState<PublishSettingsForm>({ require_manual_confirmation: true, dry_run: false, allowed_severities: "critical, high, medium, low" });
  const [dataForm, setDataForm] = useState<DataSettingsForm>({ prompt_retention: "hash_only", diff_max_lines_to_llm: "4000", sensitive_paths: "infra/secrets/**, config/prod/**, **/*.pem, **/*.p12", fallback_on_violation: "skip_file" });
  const [llmTest, setLlmTest] = useState<LlmTestState>({ status: "idle", message: "" });
  const [toolSave, setToolSave] = useState<FormActionState>({ status: "idle", message: "" });
  const [successNotice, setSuccessNotice] = useState<SuccessNotice | null>(null);
  const [agentQuality, setAgentQuality] = useState<Record<string, unknown>[]>([]);
  const [ruleDocs, setRuleDocs] = useState<Record<string, unknown>[]>([]);
  const [ruleBindings, setRuleBindings] = useState<Record<string, unknown>[]>([]);
  const [customSkills, setCustomSkills] = useState<Record<string, unknown>[]>([]);
  const [skillAssets, setSkillAssets] = useState<Record<string, unknown>[]>([]);
  const [skillBindings, setSkillBindings] = useState<Record<string, unknown>[]>([]);
  const [toolBindings, setToolBindings] = useState<Record<string, unknown>[]>([]);
  const [agentTab, setAgentTab] = useState<"create" | "list">("create");
  const [ruleContent, setRuleContent] = useState("只报告有证据、有行号、可修复的高置信问题。");
  const [ruleDocName, setRuleDocName] = useState("项目代码规范.md");
  const [ruleDocAgentKey, setRuleDocAgentKey] = useState("security_agent");
  const [customAgentKey, setCustomAgentKey] = useState("team_custom_agent");
  const [customAgentName, setCustomAgentName] = useState("团队自定义 Agent");
  const [customAgentRole, setCustomAgentRole] = useState("你是团队自定义代码检视专家，熟悉本团队业务、工程约束和代码规范。");
  const [customAgentScope, setCustomAgentScope] = useState("只检视该团队定义的职责范围内问题。");
  const [customAgentExcluded, setCustomAgentExcluded] = useState("不输出无法定位到当前 MR diff 精确行的问题，不重复输出其他专家负责的问题。");
  const [customAgentPrompt, setCustomAgentPrompt] = useState("检视时先阅读绑定的规范文档和 Skill reference，再按团队定义的职责范围逐条检查当前 MR diff；每个问题必须包含触发规则、证据、影响和建议修改代码。");
  const [customAgentLanguages, setCustomAgentLanguages] = useState("java");
  const [customAgentPaths, setCustomAgentPaths] = useState("src/main/java/**, **/*.java");
  const [customAgentTriggers, setCustomAgentTriggers] = useState("service, controller, repository");
  const [skillName, setSkillName] = useState("团队自定义检视 Skill");
  const [skillKey, setSkillKey] = useState("team-custom-review");
  const [skillAgentKey, setSkillAgentKey] = useState("team_custom_agent");
  const [skillAssetPath, setSkillAssetPath] = useState("references/team-rules.md");
  const [skillAssetSkillKey, setSkillAssetSkillKey] = useState("team-custom-review");
  const [skillAssetContent, setSkillAssetContent] = useState("## TEAM-RULE-001 团队自定义规范\n\n### 规范说明\n在这里填写团队规则说明。\n\n### 检查点\n- 检查点 1。\n- 检查点 2。\n\n### 如何检查\n1. 读取当前 MR diff。\n2. 对照规则逐条检查。\n\n### 反例\n```java\n// bad example\n```\n\n### 正例\n```java\n// good example\n```\n");
  const [skillContent, setSkillContent] = useState([
    "# 团队自定义检视 Skill",
    "",
    "## 角色增强",
    "你熟悉本团队业务、工程约束和代码规范。",
    "",
    "## 必读参考",
    "- references/team-rules.md",
    "",
    "## 检视步骤",
    "1. 调用 read_skill_asset 读取 references 下的团队规范。",
    "2. 按参考文档中的规则逐条检查当前 MR diff。",
    "3. 只输出当前 MR 新增/修改行上的高置信问题。",
    "4. 每个 finding 必须包含 covered_rules、精确行号和 suggested_code。"
  ].join("\n"));
  const [memberName, setMemberName] = useState("");
  const currentSettingsKey = `${projectId}:settings`;
  const settingsReady = view !== "settings" || settingsLoadedKey === currentSettingsKey;

  async function loadConfigView() {
    const isSettingsView = view === "settings";
    if (isSettingsView) {
      setConfigLoading(true);
      setConfigLoadError("");
      setToolchain(null);
      setStaticToolAvailability(null);
    }
    setRows([]);
    try {
      if (view === "rules") setRows(await api<Record<string, unknown>[]>(`/api/projects/${projectId}/rule-sets`));
      else if (view === "agents") {
        const [profiles, rules, bindings, expertRuleBindings, skills, assets, expertSkillBindings, qualityData] = await Promise.all([
          api<Record<string, unknown>[] | { items: Record<string, unknown>[] }>(`/api/projects/${projectId}/expert-profiles`),
          api<Record<string, unknown>[] | { items: Record<string, unknown>[] }>(`/api/projects/${projectId}/rule-documents`),
          api<Record<string, unknown>[] | { items: Record<string, unknown>[] }>(`/api/projects/${projectId}/expert-tool-bindings`),
          api<Record<string, unknown>[] | { items: Record<string, unknown>[] }>(`/api/projects/${projectId}/expert-rule-bindings`),
          api<Record<string, unknown>[] | { items: Record<string, unknown>[] }>(`/api/projects/${projectId}/custom-skills`),
          api<Record<string, unknown>[] | { items: Record<string, unknown>[] }>(`/api/projects/${projectId}/custom-skill-assets`),
          api<Record<string, unknown>[] | { items: Record<string, unknown>[] }>(`/api/projects/${projectId}/expert-skill-bindings`),
          api<Record<string, unknown>[] | { items: Record<string, unknown>[] }>(`/api/projects/${projectId}/agents/quality`)
        ]);
        setRows(listItems(profiles));
        setRuleDocs(listItems(rules));
        setToolBindings(listItems(bindings));
        setRuleBindings(listItems(expertRuleBindings));
        setCustomSkills(listItems(skills));
        setSkillAssets(listItems(assets));
        setSkillBindings(listItems(expertSkillBindings));
        setAgentQuality(listItems(qualityData));
      }
      else if (view === "users") setRows(await api<Record<string, unknown>[]>(`/api/projects/${projectId}/members`));
      else if (view === "policy") setRows([await api<Record<string, unknown>>(`/api/projects/${projectId}/review-policy`)]);
      else if (view === "tools") {
        const [data, availability] = await Promise.all([
          api<Record<string, unknown>>(`/api/projects/${projectId}/toolchain/status`),
          api<StaticToolAvailability>(`/api/projects/${projectId}/static-tools/availability`)
        ]);
        setToolchain(data);
        setStaticToolAvailability(availability);
        setRows((data.tool_calls as Record<string, unknown>[] | undefined) ?? []);
      }
      else if (view === "queue") {
        const [data, deadLetterData] = await Promise.all([
          api<Record<string, unknown>>(`/api/projects/${projectId}/queue/summary`),
          api<{ items: Record<string, unknown>[] }>(`/api/mr-review/projects/${projectId}/dead-letters`)
        ]);
        setQueueSummary(data);
        setDeadLetters(deadLetterData.items);
        setRows((data.running as Record<string, unknown>[] | undefined) ?? []);
      }
      else if (view === "settings") {
        const [settings, effective] = await Promise.all([
          api<Record<string, unknown>>(`/api/projects/${projectId}/settings`),
          api<Record<string, unknown>>(`/api/projects/${projectId}/effective-config`)
        ]);
      const items = listItems(settings as { items?: Record<string, unknown>[] });
      setRows(items);
      const settingsMap = recordValue((settings as Record<string, unknown>).settings);
      const effectiveRoot = recordValue((effective as Record<string, unknown>).effective_config);
      const llm = { ...recordValue(effectiveRoot.llm), ...recordValue(settingsMap.llm_policy) };
      const reviewPolicy = { ...recordValue(effectiveRoot.review_policy), ...recordValue(settingsMap.review_policy) };
      const agentPolicy = { ...recordValue(effectiveRoot.agent_policy), ...recordValue(settingsMap.agent_policy) };
      const toolPolicy = { ...recordValue(effectiveRoot.tool_policy), ...recordValue(settingsMap.tool_policy) };
      const queuePolicy = { ...recordValue(effectiveRoot.queue_policy), ...recordValue(settingsMap.queue_policy) };
      const publishPolicy = { ...recordValue(effectiveRoot.publish_policy), ...recordValue(settingsMap.publish_policy) };
      const dataPolicy = { ...recordValue(effectiveRoot.data_policy), ...recordValue(settingsMap.data_policy) };
      const staticRunners = recordValue(toolPolicy.static_runners);
      const semgrepRunner = recordValue(staticRunners.semgrep);
      const gitleaksRunner = recordValue(staticRunners.gitleaks);
      const checkstyleRunner = recordValue(staticRunners.checkstyle);
      const pmdRunner = recordValue(staticRunners.pmd);
      const kicsRunner = recordValue(staticRunners.kics);
      const staticToolEnabled = Object.fromEntries(
        STATIC_TOOL_SWITCHES.map((tool) => [tool.key, staticToolPolicyValue(toolPolicy, staticRunners, tool)])
      );
      setLlmForm({
        default_provider: String(llm.default_provider ?? "dashscope-openai-compatible"),
        default_base_url: String(llm.default_base_url ?? "https://ark.cn-beijing.volces.com/api/coding/v3"),
        default_model: String(llm.default_model ?? "MiniMax-M2.7"),
        default_api_key_env: String(llm.default_api_key_env ?? ""),
        default_api_key: "",
        request_timeout_seconds: String(llm.request_timeout_seconds ?? "120"),
        max_output_tokens: String(llm.max_output_tokens ?? "8192"),
        enable_stream: llm.enable_stream !== false
      });
      setLlmStoredApiKey(String(llm.default_api_key ?? ""));
      setReviewForm({
        effort: String(reviewPolicy.effort ?? "standard"),
        max_findings_per_mr: String(reviewPolicy.max_findings_per_mr ?? reviewPolicy.max_findings ?? "40"),
        min_confidence: String(reviewPolicy.min_confidence ?? "0.75"),
        enable_full_repo_context: boolValue(reviewPolicy.enable_full_repo_context, true)
      });
      setAgentForm({
        max_parallel_agents: String(agentPolicy.max_parallel_agents ?? "3"),
        enable_llm_routing: boolValue(agentPolicy.enable_llm_routing, true),
        require_rule_coverage: boolValue(agentPolicy.require_rule_coverage, true),
        default_max_tool_calls: String(agentPolicy.default_max_tool_calls ?? "12")
      });
      setToolForm({
        static_tool_enabled: staticToolEnabled,
        analysis_worktree_path: String(toolPolicy.analysis_worktree_path ?? toolPolicy.full_repo_worktree_path ?? toolPolicy.workspace_path ?? ""),
        semgrep_config: csvValue(semgrepRunner.custom_config_paths) || csvValue(semgrepRunner.additional_config_paths) || csvValue(semgrepRunner.config_paths),
        gitleaks_config_path: String(gitleaksRunner.extend_config_path ?? gitleaksRunner.custom_config_path ?? gitleaksRunner.config_path ?? toolPolicy.gitleaks_config_path ?? ""),
        checkstyle_config_path: String(checkstyleRunner.config_path ?? toolPolicy.checkstyle_config_path ?? ""),
        pmd_rulesets: csvValue(pmdRunner.custom_rulesets) || csvValue(pmdRunner.additional_rulesets) || csvValue(pmdRunner.rulesets) || String(pmdRunner.ruleset ?? toolPolicy.pmd_rulesets ?? ""),
        kics_queries_path: String(kicsRunner.custom_queries_path ?? kicsRunner.queries_path ?? ""),
        enable_mcp: boolValue(toolPolicy.enable_mcp, false),
        enable_builtin_java_heuristics: boolValue(toolPolicy.enable_builtin_java_heuristics, false)
      });
      setQueueForm({
        poll_interval_seconds: String(queuePolicy.poll_interval_seconds ?? "300"),
        max_concurrency: String(queuePolicy.max_concurrency ?? "2"),
        max_attempts: String(queuePolicy.max_attempts ?? "3"),
        heartbeat_timeout_seconds: String(queuePolicy.heartbeat_timeout_seconds ?? "600")
      });
      setPublishForm({
        require_manual_confirmation: boolValue(publishPolicy.require_manual_confirmation, true),
        dry_run: boolValue(publishPolicy.dry_run, false),
        allowed_severities: csvValue(publishPolicy.allowed_severities) || "critical, high, medium, low"
      });
      setDataForm({
        prompt_retention: String(dataPolicy.prompt_retention ?? "hash_only"),
        diff_max_lines_to_llm: String(dataPolicy.diff_max_lines_to_llm ?? "4000"),
        sensitive_paths: csvValue(dataPolicy.sensitive_paths) || "infra/secrets/**, config/prod/**, **/*.pem, **/*.p12",
        fallback_on_violation: String(dataPolicy.fallback_on_violation ?? "skip_file")
      });
      setLlmTest({ status: "idle", message: "" });
      setToolSave({ status: "idle", message: "" });
      setEffectiveConfig(effective);
        setSettingsLoadedKey(currentSettingsKey);
        Promise.all([
          api<Record<string, unknown>>(`/api/projects/${projectId}/toolchain/status`),
          api<StaticToolAvailability>(`/api/projects/${projectId}/static-tools/availability`)
        ])
          .then(([toolStatus, availability]) => {
            setToolchain(toolStatus);
            setStaticToolAvailability(availability);
          })
          .catch((error) => setMessage(error instanceof Error ? error.message : String(error)));
      } else setRows([]);
    } catch (error) {
      if (isSettingsView) setConfigLoadError(error instanceof Error ? error.message : String(error));
      throw error;
    } finally {
      if (isSettingsView) setConfigLoading(false);
    }
  }

  useEffect(() => {
    loadConfigView().catch((error) => setMessage((error as Error).message));
  }, [view, projectId]);

  async function createRule() {
    await api(`/api/projects/${projectId}/rule-sets`, {
      method: "POST",
      body: JSON.stringify({ name: `项目规则 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`, version: "draft", content: ruleContent })
    });
    setMessage("规则已创建");
    await loadConfigView();
  }

  async function uploadRuleDocument() {
    if (!ruleDocName.trim() || !ruleContent.trim()) return;
    const document = await api<Record<string, unknown>>(`/api/projects/${projectId}/rule-documents`, {
      method: "POST",
      body: JSON.stringify({
        name: ruleDocName.trim(),
        doc_type: "markdown",
        content: ruleContent,
        version: "v1",
        status: "active"
      })
    });
    if (ruleDocAgentKey) {
      await api(`/api/projects/${projectId}/expert-rule-bindings`, {
        method: "POST",
        body: JSON.stringify({ agent_key: ruleDocAgentKey, rule_document_id: document.id, priority: 100 })
      });
    }
    setMessage("规范文档已上传并绑定");
    await loadConfigView();
  }

  async function createCustomAgent() {
    if (!customAgentName.trim() || !customAgentRole.trim() || !customAgentScope.trim()) return;
    const created = await api<Record<string, unknown>>(`/api/projects/${projectId}/expert-profiles`, {
      method: "POST",
      body: JSON.stringify({
        agent_key: customAgentKey,
        display_name: customAgentName,
        role_profile: customAgentRole,
        responsibility_scope: customAgentScope,
        excluded_scope: customAgentExcluded,
        custom_prompt: customAgentPrompt,
        languages: customAgentLanguages,
        paths: customAgentPaths,
        triggers: customAgentTriggers,
        requires_deepagents: true,
        min_confidence: 0.75,
        max_findings: 12,
        max_llm_calls: 6,
        max_tool_calls: 12
      })
    });
    const agentKey = String(created.agent_key || customAgentKey);
    setRuleDocAgentKey(agentKey);
    setSkillAgentKey(agentKey);
    setAgentTab("list");
    setMessage("自定义专家 Agent 已创建，可继续绑定规范文档和 Skill");
    await loadConfigView();
  }

  async function createCustomSkill() {
    if (!skillName.trim() || !skillContent.trim()) return;
    const skill = await api<Record<string, unknown>>(`/api/projects/${projectId}/custom-skills`, {
      method: "POST",
      body: JSON.stringify({
        skill_key: skillKey.trim() || skillName.trim(),
        name: skillName.trim(),
        description: "项目级零代码自定义检视 Skill",
        content: skillContent,
        version: "v1",
        status: "active"
      })
    });
    const createdSkillKey = String(skill.skill_key || skillKey);
    await api(`/api/projects/${projectId}/custom-skill-assets`, {
      method: "POST",
      body: JSON.stringify({
        skill_key: createdSkillKey,
        asset_path: "SKILL.md",
        asset_type: "skill",
        content: skillContent,
        executable: false
      })
    });
    if (skillAgentKey) {
      await api(`/api/projects/${projectId}/expert-skill-bindings`, {
        method: "POST",
        body: JSON.stringify({ agent_key: skillAgentKey, skill_key: createdSkillKey, priority: 100, enabled: true })
      });
    }
    setMessage("自定义 Skill 已创建并绑定");
    await loadConfigView();
  }

  async function uploadSkillAsset() {
    const targetSkillKey = skillAssetSkillKey.trim() || skillKey.trim();
    if (!targetSkillKey || !skillAssetPath.trim() || !skillAssetContent.trim()) return;
    await api(`/api/projects/${projectId}/custom-skill-assets`, {
      method: "POST",
      body: JSON.stringify({
        skill_key: targetSkillKey,
        asset_path: skillAssetPath.trim(),
        content: skillAssetContent,
        executable: skillAssetPath.trim().startsWith("scripts/")
      })
    });
    setMessage("Skill 资源已保存");
    await loadConfigView();
  }

  async function addMember() {
    if (!memberName.trim()) return;
    await api(`/api/projects/${projectId}/members`, {
      method: "POST",
      body: JSON.stringify({ username: memberName.trim(), display_name: memberName.trim(), role: "developer" })
    });
    setMemberName("");
    setMessage("成员已添加");
    await loadConfigView();
  }

  async function saveStructuredSetting(key: string, label: string, value: Record<string, unknown>) {
    await api(`/api/projects/${projectId}/settings/${key}`, {
      method: "PATCH",
      body: JSON.stringify({ value })
    });
    setMessage(`${label}已保存`);
    setSuccessNotice({
      title: `${label}已保存`,
      message: "项目级配置已更新，后续该项目下的 MR 检视会使用最新配置。"
    });
    await loadConfigView();
  }

  async function saveLlmSettings() {
    await saveStructuredSetting("llm_policy", "模型服务配置", {
      default_provider: llmForm.default_provider.trim(),
      default_base_url: llmForm.default_base_url.trim(),
      default_model: llmForm.default_model.trim(),
      default_api_key_env: llmForm.default_api_key_env.trim() || null,
      default_api_key: llmForm.default_api_key.trim() || llmStoredApiKey || null,
      request_timeout_seconds: clampLlmTimeout(llmForm.request_timeout_seconds),
      max_output_tokens: clampLlmOutputTokens(llmForm.max_output_tokens),
      enable_stream: llmForm.enable_stream
    });
  }

  async function testLlmSettings() {
    setLlmTest({ status: "testing", message: "正在测试模型服务连通性..." });
    try {
      const result = await api<Record<string, unknown>>(`/api/projects/${projectId}/settings/llm/test`, {
        method: "POST",
        body: JSON.stringify({
          default_provider: llmForm.default_provider.trim(),
          default_base_url: llmForm.default_base_url.trim(),
          default_model: llmForm.default_model.trim(),
          default_api_key_env: llmForm.default_api_key_env.trim() || null,
          default_api_key: llmForm.default_api_key.trim() || llmStoredApiKey || null,
          request_timeout_seconds: clampLlmTimeout(llmForm.request_timeout_seconds),
          max_output_tokens: clampLlmOutputTokens(llmForm.max_output_tokens),
          enable_stream: llmForm.enable_stream
        })
      });
      const ok = Boolean(result.ok);
      const statusText = result.status ? `HTTP ${String(result.status)}` : "无 HTTP 状态";
      const sampleText = String(result.sample ?? "").trim();
      const streamText = result.stream === false ? "非流式" : "流式";
      const nextMessage = ok
        ? `连接成功，${statusText}，${streamText}，耗时 ${String(result.latency_ms ?? "--")}ms，模型 ${String(result.model ?? llmForm.default_model)}${sampleText ? `，返回：${sampleText}` : ""}`
        : `连接失败，${statusText}：${String(result.error_preview ?? "未知错误")}`;
      setLlmTest({
        status: ok ? "ok" : "failed",
        message: nextMessage
      });
      setMessage(nextMessage);
      if (ok) {
        setSuccessNotice({
          title: "模型连接测试成功",
          message: nextMessage,
          detail: "当前项目后续 AI 检视会使用该模型配置。"
        });
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      setLlmTest({ status: "failed", message: errorMessage });
      setMessage(errorMessage);
    }
  }

  async function saveReviewSettings() {
    await saveStructuredSetting("review_policy", "检视策略", {
      effort: reviewForm.effort,
      max_findings_per_mr: Number(reviewForm.max_findings_per_mr),
      min_confidence: Number(reviewForm.min_confidence),
      enable_full_repo_context: reviewForm.enable_full_repo_context
    });
  }

  async function saveAgentSettings() {
    await saveStructuredSetting("agent_policy", "专家 Agent 策略", {
      max_parallel_agents: Number(agentForm.max_parallel_agents),
      enable_llm_routing: agentForm.enable_llm_routing,
      require_rule_coverage: agentForm.require_rule_coverage,
      default_max_tool_calls: Number(agentForm.default_max_tool_calls)
    });
  }

  async function saveToolSettings() {
    setToolSave({ status: "saving", message: "正在保存静态工具策略..." });
    const payload = {
      analysis_worktree_path: toolForm.analysis_worktree_path.trim(),
      enable_mcp: toolForm.enable_mcp,
      enable_builtin_java_heuristics: toolForm.enable_builtin_java_heuristics,
      static_runners: staticRunnerPayload(toolForm)
    };
    try {
      await api(`/api/projects/${projectId}/settings/tool_policy`, {
        method: "PATCH",
        body: JSON.stringify({ value: payload })
      });
      setMessage("静态工具策略已保存");
      setToolSave({ status: "ok", message: "静态工具策略已保存，下一次 MR 检视会按这些开关执行。" });
      setSuccessNotice({
        title: "静态工具策略已保存",
        message: "下一次 MR 检视会按这些工具开关执行。",
        detail: `已配置 ${STATIC_TOOL_SWITCHES.length} 个静态工具开关。`
      });
      await loadConfigView();
      setToolSave({ status: "ok", message: "静态工具策略已保存，下一次 MR 检视会按这些开关执行。" });
    } catch (error) {
      setToolSave({ status: "failed", message: error instanceof Error ? error.message : String(error) });
    }
  }

  async function saveQueueSettings() {
    await saveStructuredSetting("queue_policy", "队列策略", {
      poll_interval_seconds: Number(queueForm.poll_interval_seconds),
      max_concurrency: Number(queueForm.max_concurrency),
      max_attempts: Number(queueForm.max_attempts),
      heartbeat_timeout_seconds: Number(queueForm.heartbeat_timeout_seconds)
    });
  }

  async function savePublishSettings() {
    await saveStructuredSetting("publish_policy", "发布策略", {
      require_manual_confirmation: publishForm.require_manual_confirmation,
      dry_run: publishForm.dry_run,
      allowed_severities: splitCsv(publishForm.allowed_severities)
    });
  }

  async function saveDataSettings() {
    await saveStructuredSetting("data_policy", "数据安全策略", {
      prompt_retention: dataForm.prompt_retention,
      diff_max_lines_to_llm: Number(dataForm.diff_max_lines_to_llm),
      sensitive_paths: splitCsv(dataForm.sensitive_paths),
      fallback_on_violation: dataForm.fallback_on_violation
    });
  }

  async function toggleAgent(row: Record<string, unknown>) {
    const agentKey = String(row.agent_key || row.agent_id);
    await api(`/api/projects/${projectId}/expert-profiles/${agentKey}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled: !Boolean(row.enabled) })
    });
    setMessage("Agent 配置已更新");
    await loadConfigView();
  }

  async function retryDeadLetter(row: Record<string, unknown>) {
    const jobId = String(row.review_job_id || "");
    if (!jobId) return;
    await api(`/api/mr-review/review-jobs/${jobId}/retry`, {
      method: "POST",
      body: JSON.stringify({ effort_level: "standard" })
    });
    setMessage("死信任务已重新入队");
    await loadConfigView();
  }

  function agentRuleCount(agentKey: string) {
    return agentRuleNames(agentKey).length;
  }

  function agentToolCount(agentKey: string) {
    return toolBindings.filter((binding) => String(binding.agent_key) === agentKey && Boolean(binding.enabled)).length;
  }

  function agentRuleNames(agentKey: string) {
    const boundDocIds = new Set(ruleBindings.filter((binding) => String(binding.agent_key) === agentKey).map((binding) => String(binding.rule_document_id)));
    return ruleDocs
      .filter((rule) => boundDocIds.has(String(rule.id)) || String(rule.name || "").includes(agentLabel(agentKey)) || String(rule.id || "").includes(agentKey))
      .map((rule) => String(rule.name || rule.id));
  }

  function agentToolNames(agentKey: string) {
    return toolBindings
      .filter((binding) => String(binding.agent_key) === agentKey && Boolean(binding.enabled))
      .map((binding) => `${String(binding.tool_name)} / ${String(binding.permission_level ?? "read_only")}`);
  }

  function agentSkillNames(agentKey: string) {
    const boundSkillKeys = new Set(
      skillBindings
        .filter((binding) => String(binding.agent_key) === agentKey && Boolean(binding.enabled))
        .map((binding) => String(binding.skill_key))
    );
    return customSkills
      .filter((skill) => boundSkillKeys.has(String(skill.skill_key)))
      .map((skill) => String(skill.name || skill.skill_key));
  }

  function agentSkillAssetNames(agentKey: string) {
    const boundSkillKeys = new Set(
      skillBindings
        .filter((binding) => String(binding.agent_key) === agentKey && Boolean(binding.enabled))
        .map((binding) => String(binding.skill_key))
    );
    return skillAssets
      .filter((asset) => boundSkillKeys.has(String(asset.skill_key)))
      .map((asset) => `${String(asset.skill_key)}/${String(asset.asset_path)}`);
  }

  function agentQualityRow(agentKey: string) {
    return agentQuality.find((item) => String(item.agent_id) === agentKey) ?? {};
  }

  if (view === "full" || view === "issues") {
    return (
      <section className="config-workspace">
        <ConfigHeader title={viewTitle(view)} subtitle="已按统一前端门户预留入口，后期可接入全量检视团队的任务与问题 API。" />
        <div className="config-grid">
          <ConfigCard title="接口命名空间" rows={["/api/full-review/projects/:projectId/jobs", "/api/full-review/jobs/:jobId/session-logs", "/api/full-review/snapshots/:snapshotId/findings"]} />
          <ConfigCard title="共享组件" rows={["Finding 列表", "检视过程时间线", "Agent/Tool/LLM 调用记录", "规则版本与审计日志"]} />
        </div>
      </section>
    );
  }

  return (
    <section className="config-workspace">
      <ConfigHeader title={viewTitle(view)} subtitle="项目级配置会影响该项目下所有 CodeHub 仓库的 MR 检视。" />
      {view === "repos" && (
        <div className="config-grid">
          {repos.map((repo) => <ConfigCard key={repo.id} title={repo.name} rows={[providerLabel(repo.provider), repo.external_repo_id, repo.status]} />)}
        </div>
      )}
      {view === "rules" && (
        <>
          <div className="config-editor">
            <textarea value={ruleContent} onChange={(event) => setRuleContent(event.target.value)} disabled={!canEdit} />
            <button type="button" onClick={createRule} disabled={!canEdit}>新增规则版本</button>
          </div>
          <ConfigTable rows={rows} columns={["name", "version", "status", "updated_at"]} />
        </>
      )}
      {view === "agents" && (
        <>
          <div className="agent-workspace-tabs" role="tablist" aria-label="专家 Agent 配置页签">
            <button type="button" className={agentTab === "create" ? "active" : ""} onClick={() => setAgentTab("create")}>创建 Agent</button>
            <button type="button" className={agentTab === "list" ? "active" : ""} onClick={() => setAgentTab("list")}>专家 Agent 列表</button>
          </div>
          {agentTab === "create" && (
            <div className="agent-tab-panel">
              <div className="rule-upload-panel">
                <div>
                  <strong>创建自定义专家 Agent</strong>
                  <span>零代码定义专家画像、检视 Prompt、适用语言/路径/触发词；创建后可绑定规范文档和标准 Skill bundle。</span>
                </div>
                <div className="rule-upload-form">
                  <input value={customAgentKey} onChange={(event) => setCustomAgentKey(event.target.value)} placeholder="agent-key，例如 payment_agent" disabled={!canEdit} />
                  <input value={customAgentName} onChange={(event) => setCustomAgentName(event.target.value)} placeholder="Agent 名称" disabled={!canEdit} />
                  <button type="button" onClick={createCustomAgent} disabled={!canEdit}>创建 Agent</button>
                </div>
                <div className="agent-editor-grid">
                  <label>
                    <span>Agent 画像</span>
                    <textarea value={customAgentRole} onChange={(event) => setCustomAgentRole(event.target.value)} disabled={!canEdit} />
                  </label>
                  <label>
                    <span>检视职责</span>
                    <textarea value={customAgentScope} onChange={(event) => setCustomAgentScope(event.target.value)} disabled={!canEdit} />
                  </label>
                  <label>
                    <span>排除范围</span>
                    <textarea value={customAgentExcluded} onChange={(event) => setCustomAgentExcluded(event.target.value)} disabled={!canEdit} />
                  </label>
                  <label>
                    <span>Agent Prompt</span>
                    <textarea value={customAgentPrompt} onChange={(event) => setCustomAgentPrompt(event.target.value)} disabled={!canEdit} />
                  </label>
                  <label>
                    <span>语言</span>
                    <input value={customAgentLanguages} onChange={(event) => setCustomAgentLanguages(event.target.value)} disabled={!canEdit} />
                  </label>
                  <label>
                    <span>路径匹配</span>
                    <input value={customAgentPaths} onChange={(event) => setCustomAgentPaths(event.target.value)} disabled={!canEdit} />
                  </label>
                  <label>
                    <span>触发词</span>
                    <input value={customAgentTriggers} onChange={(event) => setCustomAgentTriggers(event.target.value)} disabled={!canEdit} />
                  </label>
                </div>
              </div>
              <div className="rule-upload-panel">
                <div>
                  <strong>上传结构化 Markdown 规范</strong>
                  <span>建议使用 rule_id、适用范围、检查项、反例、修复建议等结构化段落，Agent 会逐条按规范检视。</span>
                </div>
                <div className="rule-upload-form">
                  <input value={ruleDocName} onChange={(event) => setRuleDocName(event.target.value)} disabled={!canEdit} />
                  <select value={ruleDocAgentKey} onChange={(event) => setRuleDocAgentKey(event.target.value)} disabled={!canEdit}>
                    {rows.map((row, index) => {
                      const agentKey = String(row.agent_key || row.agent_id || `agent_${index}`);
                      return <option key={agentKey} value={agentKey}>{String(row.display_name || row.agent_key || row.agent_id || agentKey)}</option>;
                    })}
                  </select>
                  <button type="button" onClick={uploadRuleDocument} disabled={!canEdit}>上传并绑定</button>
                </div>
                <textarea value={ruleContent} onChange={(event) => setRuleContent(event.target.value)} disabled={!canEdit} />
              </div>
              <div className="rule-upload-panel">
                <div>
                  <strong>创建零代码自定义 Skill</strong>
                  <span>用于补充团队业务知识、检视步骤、输出约束和特殊风险模型；绑定后下一次 MR 检视自动加载。</span>
                </div>
                <div className="rule-upload-form">
                  <input value={skillName} onChange={(event) => setSkillName(event.target.value)} placeholder="Skill 名称" disabled={!canEdit} />
                  <input value={skillKey} onChange={(event) => setSkillKey(event.target.value)} placeholder="skill-key，例如 payment-business-review" disabled={!canEdit} />
                  <select value={skillAgentKey} onChange={(event) => setSkillAgentKey(event.target.value)} disabled={!canEdit}>
                    {rows.map((row, index) => {
                      const agentKey = String(row.agent_key || row.agent_id || `agent_${index}`);
                      return <option key={agentKey} value={agentKey}>{String(row.display_name || row.agent_key || row.agent_id || agentKey)}</option>;
                    })}
                  </select>
                  <button type="button" onClick={createCustomSkill} disabled={!canEdit}>创建并绑定</button>
                </div>
                <textarea value={skillContent} onChange={(event) => setSkillContent(event.target.value)} disabled={!canEdit} />
              </div>
              <div className="rule-upload-panel">
                <div>
                  <strong>添加 Skill Bundle 资源</strong>
                  <span>支持标准路径：SKILL.md、references/*.md、scripts/*.py、assets/*。脚本默认只注册为资源，执行需后续开启沙箱策略。</span>
                </div>
                <div className="rule-upload-form">
                  <input value={skillAssetSkillKey} onChange={(event) => setSkillAssetSkillKey(event.target.value)} placeholder="skill-key" disabled={!canEdit} />
                  <input value={skillAssetPath} onChange={(event) => setSkillAssetPath(event.target.value)} placeholder="references/rules.md 或 scripts/check.py" disabled={!canEdit} />
                  <button type="button" onClick={uploadSkillAsset} disabled={!canEdit}>保存资源</button>
                </div>
                <textarea value={skillAssetContent} onChange={(event) => setSkillAssetContent(event.target.value)} disabled={!canEdit} />
              </div>
            </div>
          )}
          {agentTab === "list" && (
            <div className="agent-tab-panel">
              <div className="agent-inventory-summary">
                <span>专家 Agent <strong>{rows.length}</strong></span>
                <span>规范文档 <strong>{ruleDocs.length}</strong></span>
                <span>自定义 Skill <strong>{customSkills.length}</strong></span>
                <span>Skill 资源 <strong>{skillAssets.length}</strong></span>
              </div>
              <div className="agent-config-list">
                {rows.map((row) => (
                  <AgentProfileCard
                    key={String(row.id || row.agent_key || row.agent_id)}
                    row={row}
                    projectId={projectId}
                    ruleCount={agentRuleCount(String(row.agent_key || row.agent_id))}
                    toolCount={agentToolCount(String(row.agent_key || row.agent_id))}
                    ruleNames={agentRuleNames(String(row.agent_key || row.agent_id))}
                    toolNames={agentToolNames(String(row.agent_key || row.agent_id))}
                    skillNames={agentSkillNames(String(row.agent_key || row.agent_id))}
                    skillAssetNames={agentSkillAssetNames(String(row.agent_key || row.agent_id))}
                    quality={agentQualityRow(String(row.agent_key || row.agent_id))}
                    reload={loadConfigView}
                    setMessage={setMessage}
                    toggleAgent={toggleAgent}
                    canEdit={canEdit}
                  />
                ))}
                {!rows.length && <div className="config-table-empty">暂无专家 Agent，请先在创建页签中新增。</div>}
              </div>
            </div>
          )}
        </>
      )}
      {view === "tools" && (
        <>
          <div className="config-grid">
            <ConfigCard title="最新运行" rows={[`Run: ${String(toolchain?.latest_run_id ?? "--")}`, `工具分组: ${String(rows.length)}`, `Manifest: ${Object.keys((toolchain?.latest_manifest as Record<string, unknown>) ?? {}).join(", ") || "--"}`]} />
            <ConfigCard title="工具策略" rows={["缺失工具不阻断检视", "工具输出进入 tool_observations", "Agent/Judge 采纳后才成为 finding"]} />
          </div>
          <StaticToolAvailabilityPanel availability={staticToolAvailability} />
          <ConfigTable rows={rows} columns={["tool_name", "status", "count", "last_seen_at"]} />
        </>
      )}
      {view === "queue" && (
        <>
          <div className="config-grid">
            {((queueSummary?.by_status as Record<string, unknown>[] | undefined) ?? []).map((item) => (
              <ConfigCard key={String(item.status)} title={statusLabel(String(item.status))} rows={[`数量 ${String(item.count)}`]} />
            ))}
            <ConfigCard title="队列健康" rows={[`运行中 ${String(((queueSummary?.running as unknown[]) ?? []).length)}`, `死信 ${String(queueSummary?.dead_letter_count ?? 0)}`, `平均耗时 ${String((queueSummary?.duration as any)?.avg_duration_seconds ?? "--")}s`]} />
          </div>
          <ConfigTable rows={rows} columns={["id", "status", "attempt", "heartbeat_at", "title", "repository_name"]} />
          <div className="dead-letter-section">
            <h2>死信任务</h2>
            {deadLetters.map((item) => (
              <article key={String(item.id)}>
                <div>
                  <strong>{String(item.merge_request_title || "未知 MR")}</strong>
                  <span>{String(item.failure_reason || "--")}</span>
                </div>
                <button type="button" onClick={() => retryDeadLetter(item)} disabled={!canEdit}>重试</button>
              </article>
            ))}
            {!deadLetters.length && <div className="config-table-empty">暂无死信任务</div>}
          </div>
        </>
      )}
      {view === "users" && (
        <>
          <div className="config-editor inline">
            <input value={memberName} onChange={(event) => setMemberName(event.target.value)} placeholder="username" disabled={!canEdit} />
            <button type="button" onClick={addMember} disabled={!canEdit}>添加开发者</button>
          </div>
          <ConfigTable rows={rows} columns={["username", "display_name", "role", "status"]} />
        </>
      )}
      {view === "policy" && <ConfigTable rows={rows.map((row) => ({ ...row, policy_json: JSON.stringify(safeJson(String(row.policy_json || "{}")), null, 2) }))} columns={["project_id", "policy_json", "updated_at"]} />}
      {view === "settings" && (
        <>
          {!settingsReady && <SettingsConfigLoadingPanel loading={configLoading} error={configLoadError} onRetry={loadConfigView} />}
          {settingsReady && (
            <>
          <StaticToolAvailabilityPanel availability={staticToolAvailability} />
          <div className="settings-grid">
            <article className="setting-form-card">
              <div className="setting-form-head">
                <strong>模型服务配置</strong>
                <span>OpenAI-compatible 网关，默认用于 MiniMax-M2.7 代码检视。</span>
              </div>
              <div className="setting-form-grid">
                <SettingField label="Provider">
                  <input value={llmForm.default_provider} onChange={(event) => setLlmForm({ ...llmForm, default_provider: event.target.value })} disabled={!canEdit} />
                </SettingField>
                <SettingField label="Base URL">
                  <input value={llmForm.default_base_url} onChange={(event) => setLlmForm({ ...llmForm, default_base_url: event.target.value })} disabled={!canEdit} />
                </SettingField>
                <SettingField label="Model">
                  <input value={llmForm.default_model} onChange={(event) => setLlmForm({ ...llmForm, default_model: event.target.value })} disabled={!canEdit} />
                </SettingField>
                <SettingField label="调用超时（秒）">
                  <input type="number" min="1" max="600" value={llmForm.request_timeout_seconds} onChange={(event) => setLlmForm({ ...llmForm, request_timeout_seconds: event.target.value })} disabled={!canEdit} />
                </SettingField>
                <SettingField label="输出上限 Tokens">
                  <input type="number" min="1024" max="12000" value={llmForm.max_output_tokens} onChange={(event) => setLlmForm({ ...llmForm, max_output_tokens: event.target.value })} disabled={!canEdit} />
                </SettingField>
                <SettingField label="流式调用">
                  <label className="setting-check">
                    <input type="checkbox" checked={llmForm.enable_stream} onChange={(event) => setLlmForm({ ...llmForm, enable_stream: event.target.checked })} disabled={!canEdit} />
                    <span>启用 SSE 流式响应</span>
                  </label>
                </SettingField>
                <SettingField label="API Key 环境变量">
                  <input value={llmForm.default_api_key_env} onChange={(event) => setLlmForm({ ...llmForm, default_api_key_env: event.target.value })} placeholder="例如 MINIMAX_API_KEY" disabled={!canEdit} />
                </SettingField>
                <SettingField label="API Key">
                  <input type="password" value={llmForm.default_api_key} onChange={(event) => setLlmForm({ ...llmForm, default_api_key: event.target.value })} placeholder={llmStoredApiKey ? "已配置，留空不修改" : "本机调试可直接填写"} disabled={!canEdit} />
                </SettingField>
              </div>
              <div className="setting-actions">
                <button type="button" onClick={testLlmSettings} disabled={!canEdit || llmTest.status === "testing"}>{llmTest.status === "testing" ? "测试中..." : "测试连接"}</button>
                <button type="button" onClick={saveLlmSettings} disabled={!canEdit}>保存模型配置</button>
              </div>
              {llmTest.message && <p className={`llm-test-result ${llmTest.status}`}>{llmTest.message}</p>}
            </article>

            <article className="setting-form-card wide">
              <div className="setting-form-head">
                <strong>静态工具策略</strong>
                <span>默认加载项目内置开源规则集，项目可以追加团队自定义规则。</span>
              </div>
              <StaticToolSwitchBoard
                availability={staticToolAvailability}
                values={toolForm.static_tool_enabled}
                disabled={!canEdit}
                onChange={(toolKey, enabled) => setToolForm({
                  ...toolForm,
                  static_tool_enabled: {
                    ...toolForm.static_tool_enabled,
                    [toolKey]: enabled
                  }
                })}
              />
              <div className="setting-form-grid">
                <SettingField label="完整仓库工作区">
                  <input value={toolForm.analysis_worktree_path} onChange={(event) => setToolForm({ ...toolForm, analysis_worktree_path: event.target.value })} placeholder="可选，Windows/Linux 路径均可" disabled={!canEdit} />
                </SettingField>
                <SettingField label="Semgrep 配置">
                  <input value={toolForm.semgrep_config} onChange={(event) => setToolForm({ ...toolForm, semgrep_config: event.target.value })} placeholder="追加规则路径或 registry config，逗号分隔" disabled={!canEdit} />
                </SettingField>
                <SettingField label="Gitleaks 扩展配置">
                  <input value={toolForm.gitleaks_config_path} onChange={(event) => setToolForm({ ...toolForm, gitleaks_config_path: event.target.value })} placeholder="可选，基于 useDefault 追加自定义配置" disabled={!canEdit} />
                </SettingField>
                <SettingField label="Checkstyle 自定义配置">
                  <input value={toolForm.checkstyle_config_path} onChange={(event) => setToolForm({ ...toolForm, checkstyle_config_path: event.target.value })} placeholder="可选，例如 config/checkstyle.xml" disabled={!canEdit} />
                </SettingField>
                <SettingField label="PMD 追加 Rulesets">
                  <input value={toolForm.pmd_rulesets} onChange={(event) => setToolForm({ ...toolForm, pmd_rulesets: event.target.value })} placeholder="追加自定义 ruleset，逗号分隔" disabled={!canEdit} />
                </SettingField>
                <SettingField label="KICS 自定义 Queries">
                  <input value={toolForm.kics_queries_path} onChange={(event) => setToolForm({ ...toolForm, kics_queries_path: event.target.value })} placeholder="可选，指定团队 IaC queries 目录" disabled={!canEdit} />
                </SettingField>
                <label className="setting-check">
                  <input type="checkbox" checked={toolForm.enable_mcp} onChange={(event) => setToolForm({ ...toolForm, enable_mcp: event.target.checked })} disabled={!canEdit} />
                  <span>允许 Agent 调用 MCP 工具</span>
                </label>
                <label className="setting-check">
                  <input type="checkbox" checked={toolForm.enable_builtin_java_heuristics} onChange={(event) => setToolForm({ ...toolForm, enable_builtin_java_heuristics: event.target.checked })} disabled={!canEdit} />
                  <span>启用 Jolt 内置 Java 补充规则</span>
                </label>
              </div>
              <div className="setting-actions">
                <button type="button" onClick={saveToolSettings} disabled={!canEdit || toolSave.status === "saving"}>{toolSave.status === "saving" ? "保存中..." : "保存工具策略"}</button>
              </div>
              {toolSave.message && <p className={`llm-test-result ${toolSave.status === "saving" ? "testing" : toolSave.status}`}>{toolSave.message}</p>}
            </article>

            <article className="setting-form-card">
              <div className="setting-form-head">
                <strong>检视策略</strong>
                <span>控制单个 MR 的检视强度、置信度和问题数量。</span>
              </div>
              <div className="setting-form-grid">
                <SettingField label="检视强度">
                  <select value={reviewForm.effort} onChange={(event) => setReviewForm({ ...reviewForm, effort: event.target.value })} disabled={!canEdit}>
                    <option value="fast">fast</option>
                    <option value="standard">standard</option>
                    <option value="thorough">thorough</option>
                  </select>
                </SettingField>
                <SettingField label="最大问题数">
                  <input value={reviewForm.max_findings_per_mr} onChange={(event) => setReviewForm({ ...reviewForm, max_findings_per_mr: event.target.value })} disabled={!canEdit} />
                </SettingField>
                <SettingField label="最低置信度">
                  <input value={reviewForm.min_confidence} onChange={(event) => setReviewForm({ ...reviewForm, min_confidence: event.target.value })} disabled={!canEdit} />
                </SettingField>
                <label className="setting-check">
                  <input type="checkbox" checked={reviewForm.enable_full_repo_context} onChange={(event) => setReviewForm({ ...reviewForm, enable_full_repo_context: event.target.checked })} disabled={!canEdit} />
                  <span>允许使用完整仓库上下文</span>
                </label>
              </div>
              <div className="setting-actions">
                <button type="button" onClick={saveReviewSettings} disabled={!canEdit}>保存检视策略</button>
              </div>
            </article>

            <article className="setting-form-card">
              <div className="setting-form-head">
                <strong>专家 Agent 策略</strong>
                <span>控制专家路由、并发和工具调用预算。</span>
              </div>
              <div className="setting-form-grid">
                <SettingField label="最大并行专家">
                  <input value={agentForm.max_parallel_agents} onChange={(event) => setAgentForm({ ...agentForm, max_parallel_agents: event.target.value })} disabled={!canEdit} />
                </SettingField>
                <SettingField label="默认工具调用上限">
                  <input value={agentForm.default_max_tool_calls} onChange={(event) => setAgentForm({ ...agentForm, default_max_tool_calls: event.target.value })} disabled={!canEdit} />
                </SettingField>
                <label className="setting-check">
                  <input type="checkbox" checked={agentForm.enable_llm_routing} onChange={(event) => setAgentForm({ ...agentForm, enable_llm_routing: event.target.checked })} disabled={!canEdit} />
                  <span>启用 LLM 辅助选择专家</span>
                </label>
                <label className="setting-check">
                  <input type="checkbox" checked={agentForm.require_rule_coverage} onChange={(event) => setAgentForm({ ...agentForm, require_rule_coverage: event.target.checked })} disabled={!canEdit} />
                  <span>要求问题关联命中规范</span>
                </label>
              </div>
              <div className="setting-actions">
                <button type="button" onClick={saveAgentSettings} disabled={!canEdit}>保存 Agent 策略</button>
              </div>
            </article>

            <article className="setting-form-card">
              <div className="setting-form-head">
                <strong>队列策略</strong>
                <span>控制启动后的自动同步、后台检视并发和重试。</span>
              </div>
              <div className="setting-form-grid">
                <SettingField label="同步间隔秒">
                  <input value={queueForm.poll_interval_seconds} onChange={(event) => setQueueForm({ ...queueForm, poll_interval_seconds: event.target.value })} disabled={!canEdit} />
                </SettingField>
                <SettingField label="最大并发">
                  <input value={queueForm.max_concurrency} onChange={(event) => setQueueForm({ ...queueForm, max_concurrency: event.target.value })} disabled={!canEdit} />
                </SettingField>
                <SettingField label="最大重试">
                  <input value={queueForm.max_attempts} onChange={(event) => setQueueForm({ ...queueForm, max_attempts: event.target.value })} disabled={!canEdit} />
                </SettingField>
                <SettingField label="心跳超时秒">
                  <input value={queueForm.heartbeat_timeout_seconds} onChange={(event) => setQueueForm({ ...queueForm, heartbeat_timeout_seconds: event.target.value })} disabled={!canEdit} />
                </SettingField>
              </div>
              <div className="setting-actions">
                <button type="button" onClick={saveQueueSettings} disabled={!canEdit}>保存队列策略</button>
              </div>
            </article>

            <article className="setting-form-card">
              <div className="setting-form-head">
                <strong>发布策略</strong>
                <span>控制提交检视意见到 CodeHub 的人工确认和严重级别范围。</span>
              </div>
              <div className="setting-form-grid">
                <SettingField label="允许级别">
                  <input value={publishForm.allowed_severities} onChange={(event) => setPublishForm({ ...publishForm, allowed_severities: event.target.value })} disabled={!canEdit} />
                </SettingField>
                <label className="setting-check">
                  <input type="checkbox" checked={publishForm.require_manual_confirmation} onChange={(event) => setPublishForm({ ...publishForm, require_manual_confirmation: event.target.checked })} disabled={!canEdit} />
                  <span>提交前必须人工确认</span>
                </label>
                <label className="setting-check">
                  <input type="checkbox" checked={publishForm.dry_run} onChange={(event) => setPublishForm({ ...publishForm, dry_run: event.target.checked })} disabled={!canEdit} />
                  <span>仅 dry-run 不真实发布</span>
                </label>
              </div>
              <div className="setting-actions">
                <button type="button" onClick={savePublishSettings} disabled={!canEdit}>保存发布策略</button>
              </div>
            </article>

            <article className="setting-form-card">
              <div className="setting-form-head">
                <strong>数据安全策略</strong>
                <span>控制敏感路径、Prompt 留存和可进入模型的 diff 行数。</span>
              </div>
              <div className="setting-form-grid">
                <SettingField label="Prompt 留存">
                  <select value={dataForm.prompt_retention} onChange={(event) => setDataForm({ ...dataForm, prompt_retention: event.target.value })} disabled={!canEdit}>
                    <option value="hash_only">hash_only</option>
                    <option value="metadata_only">metadata_only</option>
                    <option value="full">full</option>
                  </select>
                </SettingField>
                <SettingField label="最大 diff 行数">
                  <input value={dataForm.diff_max_lines_to_llm} onChange={(event) => setDataForm({ ...dataForm, diff_max_lines_to_llm: event.target.value })} disabled={!canEdit} />
                </SettingField>
                <SettingField label="敏感路径">
                  <input value={dataForm.sensitive_paths} onChange={(event) => setDataForm({ ...dataForm, sensitive_paths: event.target.value })} disabled={!canEdit} />
                </SettingField>
                <SettingField label="违规处理">
                  <select value={dataForm.fallback_on_violation} onChange={(event) => setDataForm({ ...dataForm, fallback_on_violation: event.target.value })} disabled={!canEdit}>
                    <option value="skip_file">skip_file</option>
                    <option value="redact">redact</option>
                    <option value="fail_review">fail_review</option>
                  </select>
                </SettingField>
              </div>
              <div className="setting-actions">
                <button type="button" onClick={saveDataSettings} disabled={!canEdit}>保存数据策略</button>
              </div>
            </article>
          </div>
          <div className="config-grid">
            <ConfigCard title="当前模型" rows={[
              String(((effectiveConfig?.effective_config as any)?.llm)?.default_model ?? "MiniMax-M2.7"),
              String(((effectiveConfig?.effective_config as any)?.llm)?.default_base_url ?? "--")
            ]} />
            <ConfigCard title="工具安装提示" rows={[
              "semgrep: pipx install semgrep 或 pip install semgrep",
              "gitleaks: brew install gitleaks / Windows 可下载 release",
              "ruff: pip install ruff",
              "bandit: pip install bandit",
              "eslint: npm install -g eslint"
            ]} />
          </div>
          <ConfigTable rows={(toolchain?.tool_calls as Record<string, unknown>[] | undefined) ?? []} columns={["tool_name", "status", "count", "last_seen_at"]} />
            </>
          )}
        </>
      )}
      {successNotice && <SuccessNoticeModal notice={successNotice} onClose={() => setSuccessNotice(null)} />}
    </section>
  );
}

function ConfigHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="config-header">
      <h1>{title}</h1>
      <p>{subtitle}</p>
    </div>
  );
}

function SettingField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="setting-field">
      <span>{label}</span>
      {children}
    </label>
  );
}

function SettingsConfigLoadingPanel({
  loading,
  error,
  onRetry
}: {
  loading: boolean;
  error: string;
  onRetry: () => Promise<void>;
}) {
  return (
    <div className={`settings-config-loading ${error ? "failed" : ""}`}>
      <div className="settings-config-loading-icon">
        {error ? <Circle /> : <Loader2 />}
      </div>
      <div>
        <strong>{error ? "配置加载失败" : "正在加载项目真实配置"}</strong>
        <p>{error || "请稍候，当前页面会在项目级配置和有效配置返回后展示。"}</p>
      </div>
      {error && (
        <button type="button" onClick={() => { onRetry().catch(() => undefined); }} disabled={loading}>
          {loading ? "重试中..." : "重试"}
        </button>
      )}
    </div>
  );
}

function SuccessNoticeModal({ notice, onClose }: { notice: SuccessNotice; onClose: () => void }) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <section className="settings-success-modal" onClick={(event) => event.stopPropagation()}>
        <div className="settings-success-icon"><Check /></div>
        <div className="settings-success-content">
          <strong>{notice.title}</strong>
          <p>{notice.message}</p>
          {notice.detail && <span>{notice.detail}</span>}
        </div>
      </section>
    </div>
  );
}

function StaticToolSwitchBoard({
  availability,
  values,
  disabled,
  onChange
}: {
  availability: StaticToolAvailability | null;
  values: Record<string, boolean>;
  disabled: boolean;
  onChange: (toolKey: string, enabled: boolean) => void;
}) {
  const availabilityByName = new Map((availability?.items ?? []).map((item) => [item.name, item]));
  const availabilityLoaded = Boolean(availability);
  return (
    <div className="static-tool-switch-board">
      {STATIC_TOOL_SWITCHES.map((tool) => {
        const item = availabilityByName.get(tool.availabilityName);
        const enabled = values[tool.key] !== false;
        return (
          <label className={`static-tool-switch-row ${enabled ? "enabled" : "disabled"}`} key={tool.key}>
            <input
              type="checkbox"
              checked={enabled}
              disabled={disabled}
              onChange={(event) => onChange(tool.key, event.target.checked)}
            />
            <div className="static-tool-switch-main">
              <strong>{tool.displayName}</strong>
              <span>{tool.category} · {tool.requiredFor}</span>
              <em>
                {!availabilityLoaded
                  ? "正在读取安装状态"
                  : item?.available
                    ? `${item.version || "available"} · ${item.path || "--"}`
                    : item?.installHint || "未读取到安装状态"}
              </em>
            </div>
            <b className={availabilityLoaded ? item?.available ? "tool-status-tag ok" : "tool-status-tag missing" : "tool-status-tag pending"}>
              {availabilityLoaded ? item?.available ? "可用" : "缺失" : "检测中"}
            </b>
          </label>
        );
      })}
    </div>
  );
}

function StaticToolAvailabilityPanel({ availability }: { availability: StaticToolAvailability | null }) {
  const items = availability?.items ?? [];
  const grouped = items.reduce<Record<string, StaticToolAvailabilityItem[]>>((acc, item) => {
    const category = item.category || "Other";
    acc[category] = [...(acc[category] ?? []), item];
    return acc;
  }, {});
  return (
    <section className="tool-availability-panel">
      <div className="tool-availability-header">
        <div>
          <strong>静态工具可用性</strong>
          <span>
            {availability
              ? `${availability.os} · PATH 分隔符 ${availability.path_delimiter} · 已安装 ${availability.available_count}/${availability.total}`
              : "正在读取当前机器的工具状态"}
          </span>
        </div>
        <span className={(availability?.missing_count ?? 0) > 0 ? "tool-health-badge warn" : "tool-health-badge ok"}>
          {(availability?.missing_count ?? 0) > 0 ? `缺失 ${availability?.missing_count}` : "全部可用"}
        </span>
      </div>
      <div className="tool-availability-grid">
        {Object.entries(grouped).map(([category, group]) => (
          <article className="tool-category-card" key={category}>
            <div className="tool-category-title">
              <strong>{category}</strong>
              <span>{group.filter((item) => item.available).length}/{group.length}</span>
            </div>
            {group.map((item) => (
              <div className="tool-status-row" key={item.name}>
                <span className={item.available ? "tool-dot ok" : "tool-dot missing"} />
                <div>
                  <strong>{item.displayName}</strong>
                  <span>{item.requiredFor}</span>
                  <em>{item.available ? `${item.version || "available"} · ${item.path || "--"}` : item.installHint}</em>
                </div>
                <b className={item.available ? "tool-status-tag ok" : "tool-status-tag missing"}>{item.available ? "可用" : "缺失"}</b>
              </div>
            ))}
          </article>
        ))}
        {!items.length && <div className="config-table-empty">暂无工具状态</div>}
      </div>
    </section>
  );
}

function ConfigCard({ title, rows }: { title: string; rows: string[] }) {
  return (
    <article className="config-card">
      <strong>{title}</strong>
      {rows.map((row, index) => <span key={`${title}-${index}-${row ?? ""}`}>{row}</span>)}
    </article>
  );
}

function ConfigTable({ rows, columns }: { rows: Record<string, unknown>[]; columns: string[] }) {
  return (
    <div className="config-table">
      <div className="config-table-head">
        {columns.map((column) => <span key={column}>{column}</span>)}
      </div>
      {rows.map((row, index) => (
        <div className="config-table-row" key={String(row.id ?? index)}>
          {columns.map((column) => <span key={column}>{String(row[column] ?? "--")}</span>)}
        </div>
      ))}
      {!rows.length && <div className="config-table-empty">暂无数据</div>}
    </div>
  );
}

function AgentProfileCard({
  row,
  projectId,
  ruleCount,
  toolCount,
  ruleNames,
  toolNames,
  skillNames,
  skillAssetNames,
  quality,
  reload,
  setMessage,
  toggleAgent,
  canEdit
}: {
  row: Record<string, unknown>;
  projectId: string;
  ruleCount: number;
  toolCount: number;
  ruleNames: string[];
  toolNames: string[];
  skillNames: string[];
  skillAssetNames: string[];
  quality: Record<string, unknown>;
  reload: () => Promise<void>;
  setMessage: (value: string) => void;
  toggleAgent: (row: Record<string, unknown>) => Promise<void>;
  canEdit: boolean;
}) {
  const agentKey = String(row.agent_key || row.agent_id);
  const [roleProfile, setRoleProfile] = useState(String(row.role_profile || row.name || ""));
  const [responsibilityScope, setResponsibilityScope] = useState(String(row.responsibility_scope || ""));
  const [excludedScope, setExcludedScope] = useState(String(row.excluded_scope || ""));
  const [minConfidence, setMinConfidence] = useState(String(row.min_confidence ?? "0.75"));
  const [maxFindings, setMaxFindings] = useState(String(row.max_findings ?? "12"));
  const [maxLlmCalls, setMaxLlmCalls] = useState(String(row.max_llm_calls ?? "6"));
  const [maxToolCalls, setMaxToolCalls] = useState(String(row.max_tool_calls ?? "12"));

  async function saveProfile() {
    await api(`/api/projects/${projectId}/expert-profiles/${agentKey}`, {
      method: "PATCH",
      body: JSON.stringify({
        role_profile: roleProfile,
        responsibility_scope: responsibilityScope,
        excluded_scope: excludedScope,
        min_confidence: Number(minConfidence),
        max_findings: Number(maxFindings),
        max_llm_calls: Number(maxLlmCalls),
        max_tool_calls: Number(maxToolCalls)
      })
    });
    setMessage("专家画像已保存");
    await reload();
  }

  return (
    <article className="agent-config-card">
      <div className="agent-card-main">
        <div className="agent-card-title">
          <strong>{String(row.display_name)}</strong>
          <span className={Boolean(row.enabled) ? "state-pill on" : "state-pill"}>{Boolean(row.enabled) ? "启用" : "停用"}</span>
        </div>
        <div className="agent-editor-grid">
          <label>
            <span>角色画像</span>
            <textarea value={roleProfile} onChange={(event) => setRoleProfile(event.target.value)} disabled={!canEdit} />
          </label>
          <label>
            <span>职责范围</span>
            <textarea value={responsibilityScope} onChange={(event) => setResponsibilityScope(event.target.value)} disabled={!canEdit} />
          </label>
          <label>
            <span>排除范围</span>
            <textarea value={excludedScope} onChange={(event) => setExcludedScope(event.target.value)} disabled={!canEdit} />
          </label>
          <label>
            <span>置信度阈值</span>
            <input value={minConfidence} onChange={(event) => setMinConfidence(event.target.value)} disabled={!canEdit} />
          </label>
          <label>
            <span>最大问题数</span>
            <input value={maxFindings} onChange={(event) => setMaxFindings(event.target.value)} disabled={!canEdit} />
          </label>
          <label>
            <span>LLM 调用上限</span>
            <input value={maxLlmCalls} onChange={(event) => setMaxLlmCalls(event.target.value)} disabled={!canEdit} />
          </label>
          <label>
            <span>工具调用上限</span>
            <input value={maxToolCalls} onChange={(event) => setMaxToolCalls(event.target.value)} disabled={!canEdit} />
          </label>
        </div>
        <div className="agent-binding-grid">
          <div>
            <strong>绑定规范</strong>
            {(ruleNames.length ? ruleNames : ["未绑定规范文档"]).map((name, index) => <span key={`${agentKey}-rule-${index}-${name}`}>{name}</span>)}
          </div>
          <div>
            <strong>绑定工具</strong>
            {(toolNames.length ? toolNames : ["未绑定工具"]).map((name, index) => <span key={`${agentKey}-tool-${index}-${name}`}>{name}</span>)}
          </div>
          <div>
            <strong>绑定 Skill</strong>
            {(skillNames.length ? skillNames : ["未绑定自定义 Skill"]).map((name, index) => <span key={`${agentKey}-skill-${index}-${name}`}>{name}</span>)}
          </div>
          <div>
            <strong>Skill 资源</strong>
            {(skillAssetNames.length ? skillAssetNames : ["未绑定 Skill 资源"]).map((name, index) => <span key={`${agentKey}-asset-${index}-${name}`}>{name}</span>)}
          </div>
        </div>
        <div className="agent-metrics-line">
          <span>规则 {ruleCount}</span>
          <span>Skill {skillNames.length}</span>
          <span>工具 {toolCount}</span>
          <span>问题 {String(quality.finding_count ?? 0)}</span>
          <span>误报率 {String(quality.false_positive_rate ?? "--")}</span>
        </div>
      </div>
      <div className="agent-card-actions">
        <button type="button" onClick={() => toggleAgent(row)} disabled={!canEdit}>{Boolean(row.enabled) ? "停用" : "启用"}</button>
        <button type="button" onClick={saveProfile} disabled={!canEdit}>保存</button>
      </div>
    </article>
  );
}

function MrQueue({
  items,
  activeMrId,
  openMr,
  previewMr,
  statusFilter,
  setStatusFilter,
  repoFilter,
  setRepoFilter,
  authorFilter,
  setAuthorFilter,
  timeFilter,
  setTimeFilter,
  repos,
  authors,
  stats,
  sync,
  syncing,
  busy,
  pendingMrActions,
  startReview,
  pauseReview,
  stopReview,
  rerunReview,
  deleteMr
}: {
  items: MergeRequest[];
  activeMrId: string | null;
  openMr: (id: string) => void;
  previewMr: (id: string) => void;
  statusFilter: string;
  setStatusFilter: (value: string) => void;
  repoFilter: string;
  setRepoFilter: (value: string) => void;
  authorFilter: string;
  setAuthorFilter: (value: string) => void;
  timeFilter: string;
  setTimeFilter: (value: string) => void;
  repos: Repo[];
  authors: string[];
  stats: { all: number; queued: number; reviewing: number; waiting: number; highRisk: number; submitted: number };
  sync: () => void;
  syncing: boolean;
  busy: boolean;
  pendingMrActions: Record<string, MrActionState>;
  startReview: (mrId: string) => void;
  pauseReview: (mrId: string) => void;
  stopReview: (mrId: string) => void;
  rerunReview: (mrId: string) => void;
  deleteMr: (mr: MergeRequest) => void;
}) {
  const tabs = [
    ["all", "全部", stats.all],
    ["queued", "待检视", stats.queued],
    ["reviewing", "检视中", stats.reviewing],
    ["waiting_confirmation", "待确认", stats.waiting],
    ["submitted", "已提交", stats.submitted]
  ] as const;

  return (
    <section className="queue-panel">
      <div className="panel-heading">
        <h1>待检视 MR</h1>
      </div>
      <div className="segmented-tabs">
        {tabs.map(([key, label, count]) => (
          <button key={key} className={statusFilter === key ? "active" : ""} onClick={() => setStatusFilter(key)}>
            {label}
            <strong>{count}</strong>
          </button>
        ))}
      </div>
      <div className="filters">
        <FilterSelect
          label="状态"
          value={statusFilter}
          onChange={setStatusFilter}
          options={[
            ["all", "全部状态"],
            ["queued", "待检视"],
            ["reviewing", "检视中"],
            ["waiting_confirmation", "待确认"],
            ["submitted", "已提交"]
          ]}
        />
        <FilterSelect
          label="作者"
          value={authorFilter}
          onChange={setAuthorFilter}
          options={[
            ["all", "全部作者"],
            ...authors.map((author) => [author, author] as [string, string])
          ]}
        />
        <FilterSelect
          label="时间"
          value={timeFilter}
          onChange={setTimeFilter}
          options={[
            ["all", "全部时间"],
            ["today", "今天"],
            ["7d", "近 7 天"],
            ["30d", "近 30 天"]
          ]}
        />
        <FilterSelect
          label="仓库"
          value={repoFilter}
          onChange={setRepoFilter}
          options={[
            ["all", "全部仓库"],
            ...repos.map((repo) => [repo.id, repo.name] as [string, string])
          ]}
        />
        <button className="filter-icon" type="button" onClick={sync} disabled={syncing}>
          {syncing ? <Loader2 className="spin" size={18} /> : <RefreshCw size={18} />}
        </button>
      </div>
      <div className="mr-table">
        <div className="mr-head">
          <span>MR</span>
          <span>仓库</span>
          <span>作者</span>
          <span>风险</span>
          <span>状态</span>
          <span>问题</span>
          <span>更新时间</span>
          <span>操作</span>
        </div>
        <div className="mr-body">
          {items.map((mr) => {
            const action = pendingMrActions[mr.id];
            const displayStatus = action === "pause" ? "paused" : action === "stop" ? "cancelled" : action ? "reviewing" : mr.review_status;
            const rowBusy = Boolean(action);
            return (
              <div
                className={`mr-row ${activeMrId === mr.id ? "active" : ""} ${rowBusy ? "pending-action" : ""}`}
                key={mr.id}
                onClick={() => openMr(mr.id)}
              >
                <span className="mr-title">
                  <strong>!{mr.number}</strong>
                  {mr.title}
                </span>
                <span>{mr.repository_name}</span>
                <span>{mr.author}</span>
                <RiskBadge score={mr.risk_score} />
                <StatusBadge status={displayStatus} />
                <span>{mr.finding_count || (displayStatus === "queued" ? "--" : 0)}</span>
                <span>{shortTime(mr.updated_at)}</span>
                <span className="mr-actions">
                  <button
                    className="mr-action-button"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      startReview(mr.id);
                    }}
                    disabled={busy || rowBusy || ACTIVE_REVIEW_STATUSES.includes(displayStatus)}
                  >
                    {action === "start" ? "启动中" : "开始"}
                  </button>
                  <button
                    className="mr-action-button"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      pauseReview(mr.id);
                    }}
                    disabled={busy || rowBusy || !["queued", ...ACTIVE_REVIEW_STATUSES].includes(displayStatus)}
                  >
                    {action === "pause" ? "暂停中" : "暂停"}
                  </button>
                  <button
                    className="mr-action-button danger"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      stopReview(mr.id);
                    }}
                    disabled={busy || rowBusy || ["waiting_confirmation", "submitted", "no_issue", "cancelled"].includes(displayStatus)}
                  >
                    {action === "stop" ? "停止中" : "停止"}
                  </button>
                  <button
                    className="mr-action-button subtle"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      rerunReview(mr.id);
                    }}
                    disabled={busy || rowBusy || ACTIVE_REVIEW_STATUSES.includes(displayStatus)}
                  >
                    {action === "rerun" ? "提交中" : "重检"}
                  </button>
                  <button
                    className="mr-action-button subtle"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      previewMr(mr.id);
                    }}
                  >
                    Diff
                  </button>
                  <button
                    className="mr-action-button icon danger"
                    type="button"
                    title="删除本地 MR"
                    aria-label={`删除 MR !${mr.number}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      deleteMr(mr);
                    }}
                    disabled={busy || rowBusy || ACTIVE_REVIEW_STATUSES.includes(displayStatus)}
                  >
                    <Trash2 size={15} />
                  </button>
                </span>
              </div>
            );
          })}
          {!items.length && <div className="table-empty">暂无 MR，请绑定 Git 仓库链接后同步。</div>}
        </div>
      </div>
      <div className="table-footer">
        <span>共 {items.length} 条</span>
        <div className="pager">
          <button disabled><ChevronLeft size={16} /></button>
          <button className="active">1</button>
          <button disabled><ChevronRight size={16} /></button>
        </div>
        <button className="page-size">20 条/页 <ChevronDown size={14} /></button>
      </div>
    </section>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange
}: {
  label: string;
  value: string;
  options: Array<[string, string]>;
  onChange: (value: string) => void;
}) {
  return (
    <label className="filter-select">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>{optionLabel}</option>
        ))}
      </select>
    </label>
  );
}

function RiskBadge({ score }: { score: number }) {
  const level = riskLevel(score);
  const text = level === "high" ? "高" : level === "medium" ? "中" : "低";
  return <span className={`risk-badge ${level}`}>{text}</span>;
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`status-badge ${status}`}>{statusLabel(status)}</span>;
}

function DetailPanel({
  detail,
  busy,
  onRerun,
  onToggleFinding,
  onToggleAllFindings,
  onFalsePositive,
  onBulkFalsePositive,
  onExportMarkdown,
  onPublish,
  projectId
}: {
  detail: Detail | null;
  busy: boolean;
  onRerun: () => void;
  onToggleFinding: (finding: Finding) => void;
  onToggleAllFindings: (selected: boolean) => void;
  onFalsePositive: (finding: Finding) => void;
  onBulkFalsePositive: () => void;
  onExportMarkdown: () => void;
  onPublish: () => void;
  projectId: string;
}) {
  const [tab, setTab] = useState<"findings" | "process" | "tools">("findings");
  const [activeFinding, setActiveFinding] = useState<Finding | null>(null);

  if (!detail) {
    return (
      <section className="detail-panel empty-detail">
        <Circle size={34} />
        <strong>选择一个 MR</strong>
        <span>右侧将展示检视进度、问题和提交操作。</span>
      </section>
    );
  }

  const hasRun = detail.runs.length > 0;
  const selectedCount = detail.findings.filter((finding) => finding.selected).length;
  const allSelected = detail.findings.length > 0 && selectedCount === detail.findings.length;
  const highCount = detail.findings.filter((finding) => finding.severity === "high" || finding.severity === "critical").length;
  const agentCount = new Set(detail.findings.map((finding) => finding.agent_id)).size || (hasRun ? 3 : 0);
  const duration = estimateDuration(detail);
  const currentStatus = effectiveReviewStatus(detail);
  const sortedFindings = sortFindingsBySeverity(detail.findings);

  return (
    <section className="detail-panel">
      <div className="detail-content">
        <div className="detail-title">
          <h2>!{detail.mr.number} {detail.mr.title}</h2>
          <p>
            <span>{detail.mr.source_branch}</span>
            <ChevronRight size={14} />
            <a href={detail.mr.html_url} target="_blank" rel="noreferrer">{detail.mr.target_branch}</a>
            <span>·</span>
            <span>{detail.mr.repository_name}</span>
            <span>·</span>
            <span>{detail.mr.author}</span>
            <span>· 风险分</span>
            <strong className={`risk-score ${riskLevel(detail.mr.risk_score)}`}>{detail.mr.risk_score}</strong>
          </p>
        </div>

        <ReviewProgressPanel detail={detail} status={currentStatus} />

        <div className="metric-row">
          <MetricCard icon={<Code2 />} value={detail.findings.length} label="个问题" sub="待确认问题" />
          <MetricCard icon={<ShieldCheck />} value={highCount} label="高危" sub="高危问题" danger />
          <MetricCard icon={<Users />} value={agentCount} label="个 Agent" sub="参与检视" />
          <MetricCard icon={<Clock3 />} value={duration} label="" sub="检视耗时" />
        </div>

        <div className="detail-tabs">
          {[
            ["findings", "检视问题"],
            ["process", "检视过程"],
            ["tools", `工具结果 (${detail.tool_observations?.length || 0})`]
          ].map(([key, label]) => (
            <button key={key} type="button" className={tab === key ? "active" : ""} onClick={() => setTab(key as typeof tab)}>
              {label}
            </button>
          ))}
        </div>

        {tab === "findings" && (
          <div className="findings-list">
            {sortedFindings.map((finding) => (
              <FindingRow
                key={finding.id}
                finding={finding}
                onToggle={() => onToggleFinding(finding)}
                onFalsePositive={() => onFalsePositive(finding)}
                onOpen={() => setActiveFinding(finding)}
              />
            ))}
            {hasRun && <CoverageCard run={detail.runs[0]} />}
            {!detail.findings.length && !hasRun && (
              <div className="empty-finding pending">
                <Loader2 className="spin" size={22} />
                <strong>检视任务尚未完成</strong>
                <span>该 MR 已提交检视，系统会先读取代码变更，再进行工具检查和 AI 专家分析。</span>
              </div>
            )}
          </div>
        )}

        {tab === "process" && <ProcessTimeline detail={detail} />}
        {tab === "tools" && <ToolResultsPanel detail={detail} onOpenFinding={setActiveFinding} />}
      </div>

      <div className="detail-actions">
        <button type="button" onClick={() => onToggleAllFindings(!allSelected)} disabled={busy || !detail.findings.length}>
          <Check size={18} />
          {allSelected ? "取消全选" : "全选问题"}
        </button>
        <button type="button" onClick={onBulkFalsePositive} disabled={busy || !selectedCount}>标记误报</button>
        <button type="button" onClick={onExportMarkdown} disabled={busy || !detail.findings.length}>
          <FileDown size={18} />
          导出 MD
        </button>
        <button type="button" onClick={onRerun} disabled={busy}>重新检视</button>
        <button className="submit-button" type="button" onClick={onPublish} disabled={busy || !selectedCount}>
          <Send size={18} />
          提交选中意见到 CodeHub
        </button>
      </div>
      {activeFinding && (
        <FindingDetailModal
          finding={activeFinding}
          mr={detail.mr}
          projectId={projectId}
          onClose={() => setActiveFinding(null)}
        />
      )}
    </section>
  );
}

function ReviewProgressPanel({ detail, status }: { detail: Detail; status: string }) {
  const index = reviewStepIndex(status);
  const latestJob = detail.jobs?.[0] || {};
  const latestRun = detail.runs?.[0] || {};
  const sessionLogs = detail.session_logs;
  const toolCount = sessionLogs?.tool_calls?.length || detail.tool_observations?.length || 0;
  const llmCount = sessionLogs?.llm_calls?.length || 0;
  const agentMessages = sessionLogs?.messages?.length || 0;
  const percent = Math.round((index / (REVIEW_STEPS.length - 1)) * 100);
  return (
    <section className="review-progress-card">
      <div className="review-progress-head">
        <div>
          <span>当前检视进度</span>
          <strong>{REVIEW_STEPS[index]?.label || statusLabel(status)}</strong>
          <p>{REVIEW_STEPS[index]?.description || statusLabel(status)}</p>
        </div>
        <StatusBadge status={status} />
      </div>
      <div className="review-progress-bar" aria-label={`检视进度 ${percent}%`}>
        <span style={{ width: `${percent}%` }} />
      </div>
      <div className="review-step-grid">
        {REVIEW_STEPS.map((step, stepIndex) => (
          <div className={`${stepIndex <= index ? "active" : ""} ${stepIndex === index ? "current" : ""}`} key={step.key}>
            <span>{stepIndex < index ? <Check size={13} /> : stepIndex + 1}</span>
            <strong>{step.label}</strong>
          </div>
        ))}
      </div>
      <div className="review-progress-meta">
        <p><strong>Job</strong><span>{String(latestJob.id || "--")}</span></p>
        <p><strong>Run</strong><span>{String(latestRun.id || "--")}</span></p>
        <p><strong>工具调用</strong><span>{toolCount}</span></p>
        <p><strong>LLM 调用</strong><span>{llmCount}</span></p>
        <p><strong>Agent 消息</strong><span>{agentMessages}</span></p>
      </div>
    </section>
  );
}

function CoverageCard({ run }: { run?: Record<string, unknown> }) {
  const coverage = safeJson(String(run?.coverage_json || "{}"));
  const tools = Array.isArray(coverage.tools) ? coverage.tools as Array<Record<string, unknown>> : [];
  const agents = Array.isArray(coverage.agents_executed) ? coverage.agents_executed.map((item) => String(item)) : [];
  return (
    <div className="coverage-card">
      <div>
        <CheckCircle2 size={22} />
        <strong>检视覆盖情况</strong>
        <span>来自本次真实工具调用、工具观察和 Agent trace。</span>
      </div>
      {tools.slice(0, 8).map((tool) => (
        <p key={String(tool.id)}>
          <Check size={15} />
          <span>{String(tool.id)}</span>
          <em>{String(tool.completed_calls || 0)} completed · {String(tool.skipped_calls || 0)} skipped</em>
          <strong>{String(tool.hits || 0)} 命中</strong>
        </p>
      ))}
      {!tools.length && <p><Check size={15} /><span>暂无 coverage_json</span><em>等待检视完成</em><strong>--</strong></p>}
      {agents.length > 0 && (
        <p>
          <Check size={15} />
          <span>专家 Agent</span>
          <em>{agents.slice(0, 4).map(agentLabel).join(", ")}</em>
          <strong>{agents.length} 个</strong>
        </p>
      )}
    </div>
  );
}

function ReviewRunCompare({ compare }: { compare?: Detail["compare"] }) {
  if (!compare?.head_run) {
    return <div className="empty-finding">暂无可对比的检视记录</div>;
  }
  return (
    <div className="compare-grid">
      <CompareColumn title="新增问题" tone="danger" items={compare.added || []} />
      <CompareColumn title="已解决" tone="success" items={compare.resolved || []} />
      <CompareColumn title="仍存在" tone="muted" items={compare.retained || []} />
    </div>
  );
}

function CompareColumn({ title, tone, items }: { title: string; tone: "danger" | "success" | "muted"; items: Finding[] }) {
  return (
    <section className={`compare-column ${tone}`}>
      <h3>{title}<strong>{items.length}</strong></h3>
      {items.slice(0, 12).map((finding) => (
        <article key={finding.id}>
          <SeverityBadge severity={finding.severity} />
          <strong>{finding.title}</strong>
          <span>{formatFindingLocation(finding)}</span>
        </article>
      ))}
      {!items.length && <p>无变化</p>}
    </section>
  );
}

function ProcessTimeline({ detail }: { detail: Detail }) {
  const isSummaryNoise = (row: Record<string, unknown>) =>
    String(row.span_key || "").includes("summarize_pr") ||
    String(row.agent_id || "").includes("summary_agent");
  const trace = (detail.trace || []).filter((row) => !isSummaryNoise(row));
  const sessionLogs = detail.session_logs;
  const toolCalls = (sessionLogs?.tool_calls || []).filter((row) => !isSummaryNoise(row));
  const staticToolCalls = toolCalls.filter((row) => String(row.tool_name || "").startsWith("static."));
  const latestJob = detail.jobs?.[0] || {};
  const latestRun = detail.runs?.[0] || {};
  const status = effectiveReviewStatus(detail);
  const groups = [
    ["Agent 对话", (sessionLogs?.messages || []).filter((row) => !isSummaryNoise(row)), "content_summary"],
    ["工具调用", toolCalls, "output_summary"],
    ["LLM 调用", (sessionLogs?.llm_calls || []).filter((row) => !isSummaryNoise(row)), "status"],
    ["MCP 调用", (sessionLogs?.mcp_calls || []).filter((row) => !isSummaryNoise(row)), "status"],
    ["Artifacts", sessionLogs?.artifacts || [], "name"]
  ] as const;
  return (
    <div className="process-panel">
      <section className="process-overview">
        <div>
          <span>检视阶段</span>
          <strong>{statusLabel(status)}</strong>
          <p>{REVIEW_STEPS[reviewStepIndex(status)]?.description || "等待检视状态刷新"}</p>
        </div>
        <p><strong>Job 状态</strong><span>{String(latestJob.status || "--")}</span></p>
        <p><strong>Run 状态</strong><span>{String(latestRun.status || "--")}</span></p>
        <p><strong>Trace</strong><span>{trace.length} 条</span></p>
        <p><strong>Tool</strong><span>{sessionLogs?.tool_calls?.length || detail.tool_observations?.length || 0} 次</span></p>
        <p><strong>LLM</strong><span>{sessionLogs?.llm_calls?.length || 0} 次</span></p>
      </section>
      <div className="process-list">
        {trace.slice(0, 80).map((item, index) => (
          <article key={index}>
            <span />
            <div>
              <strong>{String(item.span_key || item.event_type || "trace")}</strong>
              <p>{String(item.summary || item.status || "执行记录")}</p>
              <small>{String(item.agent_id || item.event_type || "system")}</small>
            </div>
          </article>
        ))}
        {!trace.length && <div className="process-empty">当前阶段尚未写入 trace，列表状态会随 Job 状态实时刷新。</div>}
      </div>
      <section className="static-tool-detail">
        <h4>静态工具调用明细<strong>{staticToolCalls.length}</strong></h4>
        <div className="static-tool-table">
          <div className="static-tool-head">
            <span>工具</span>
            <span>状态</span>
            <span>耗时</span>
            <span>输出</span>
            <span>Artifact</span>
          </div>
          {staticToolCalls.map((row, index) => {
            const outputRef = safeJson(String(row.output_ref_json || "{}"));
            const artifact = String(outputRef.path || outputRef.artifact || "--");
            return (
              <div className="static-tool-row" key={`${String(row.tool_name)}-${index}`}>
                <strong>{String(row.tool_name || "--")}</strong>
                <em className={`tool-run-status ${String(row.status || "").replace(/[^a-z0-9_-]/gi, "_")}`}>{String(row.status || "--")}</em>
                <span>{formatDurationMs(row.duration_ms)}</span>
                <p>{String(row.output_summary || "--")}</p>
                <small title={artifact}>{artifact}</small>
              </div>
            );
          })}
          {!staticToolCalls.length && <div className="static-tool-empty">本次还没有静态工具调用记录</div>}
        </div>
      </section>
      <div className="session-grid">
        {groups.map(([title, rows, summaryKey]) => (
          <section key={title}>
            <h4>{title}<strong>{rows.length}</strong></h4>
            {rows.slice(0, 4).map((row, index) => (
              <p key={index}>
                <span>{String(row.span_key || row.tool_name || row.model || row.artifact_type || row.from_agent || title)}</span>
                <em>{String(row[summaryKey] || row.status || row.output_summary || row.storage_uri || "--")}</em>
              </p>
            ))}
            {!rows.length && <p><span>--</span><em>本次未调用</em></p>}
          </section>
        ))}
      </div>
    </div>
  );
}

function ContextRules({ runs, mr }: { runs: Array<Record<string, unknown>>; mr: MergeRequest }) {
  const run = runs[0];
  const policy = safeJson(String(run?.data_policy_snapshot || "{}"));
  const budget = safeJson(String(run?.budget_json || "{}"));
  const budgetUsed = safeJson(String(run?.budget_used_json || "{}"));
  const budgetStatus = budgetUsed.truncated_reason
    ? `已截断 ${String(budgetUsed.truncated_reason)}`
    : "未截断";
  return (
    <div className="context-panel">
      <p><strong>规则来源</strong><span>{String(run?.rule_version_source || "target_branch")}</span></p>
      <p><strong>检视强度</strong><span>{String(run?.effort_level || "standard")}</span></p>
      <p><strong>Sandbox</strong><span>{String(run?.sandbox_uri || "--")}</span></p>
      <p><strong>数据策略</strong><span>{String(policy.default_llm_provider || "internal-minimax-2.7")} · {String(policy.prompt_retention || "hash_only")}</span></p>
      <p><strong>预算策略</strong><span>{String(budget.effort || run?.effort_level || "standard")} · ${String(budget.max_cost_usd ?? "--")} · {String(budget.max_wall_seconds || "--")}s</span></p>
      <p><strong>预算用量</strong><span>{String(budgetUsed.llm_calls || 0)} calls · ${String(budgetUsed.cost_usd ?? "0")} · {budgetStatus}</span></p>
      <p><strong>目标仓库</strong><span>{mr.repository_name} · {mr.target_branch}</span></p>
    </div>
  );
}

function MetricCard({ icon, value, label, sub, danger }: { icon: React.ReactElement<{ size?: number }>; value: number | string; label: string; sub: string; danger?: boolean }) {
  return (
    <div className="metric-card">
      <span className={`metric-icon ${danger ? "danger" : ""}`}>{React.cloneElement(icon, { size: 30 })}</span>
      <strong>{value} {label}</strong>
      <small>{sub}</small>
    </div>
  );
}

function FindingRow({
  finding,
  onToggle,
  onFalsePositive,
  onOpen
}: {
  finding: Finding;
  onToggle: () => void;
  onFalsePositive: () => void;
  onOpen: () => void;
}) {
  const source = findingSource(finding);
  return (
    <article className="finding-row" onClick={onOpen} role="button" tabIndex={0} onKeyDown={(event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onOpen();
      }
    }}>
      <label onClick={(event) => event.stopPropagation()}>
        <input type="checkbox" checked={Boolean(finding.selected)} onChange={onToggle} />
        <SeverityBadge severity={finding.severity} />
      </label>
      <span className="agent-pill">{agentLabel(finding.agent_id)}</span>
      <span className={`finding-source-tag ${source.type}`} title={source.detail}>{source.label}</span>
      <span className="confidence">{finding.confidence.toFixed(2)}</span>
      <div className="finding-main">
        <div className="finding-location-line">
          <a title={finding.file_path}>{finding.file_path || "未定位文件"}</a>
          <span>{formatFindingLineRange(finding)}</span>
        </div>
        <strong>{finding.title}</strong>
        <small className="finding-description">{finding.problem_description || finding.recommendation || "暂无问题描述"}</small>
      </div>
      <button type="button" onClick={(event) => {
        event.stopPropagation();
        onFalsePositive();
      }}>{finding.lifecycle_state === "false_positive" ? "已误报" : "标误报"}</button>
    </article>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  return <span className={`severity-badge ${severity}`}>{severityText(severity)}</span>;
}

function FindingDetailModal({
  finding,
  mr,
  projectId,
  onClose
}: {
  finding: Finding;
  mr: MergeRequest;
  projectId: string;
  onClose: () => void;
}) {
  const [sourceCode, setSourceCode] = useState("");
  const [sourcePatch, setSourcePatch] = useState("");
  const [sourceByPath, setSourceByPath] = useState<Record<string, string>>({});
  const [patchByPath, setPatchByPath] = useState<Record<string, string>>({});
  const [sourceLoading, setSourceLoading] = useState(false);
  const [ruleDetails, setRuleDetails] = useState<RuleDetail[]>([]);
  const [ruleDetailsLoading, setRuleDetailsLoading] = useState(false);
  const coveredRules = parseJsonArray(finding.covered_rules_json);
  const skippedRules = parseJsonArray(finding.skipped_rules_json);
  const sourceObservations = parseJsonObjectArray(finding.source_observations_json);
  const toolProvenance = parseJsonObjectArray(finding.tool_provenance_json);
  const qualityTrace = safeJson(String(finding.quality_trace_json || "{}"));
  const traceLocation = qualityTrace.location as Record<string, unknown> | undefined;
  const location = formatFindingLocation(finding);
  const suggestedCode = (finding.suggested_code || extractSuggestedCode(finding.recommendation)).trim();
  const primaryRules = coveredRules.length ? coveredRules : ["未声明具体 rule_id"];
  const ruleKey = primaryRules.join(",");
  const sourcePaths = Array.from(new Set(
    [
      finding.file_path,
      ...sourceObservations.map(observationFilePath)
    ].map((value) => String(value || "").trim()).filter(Boolean)
  ));
  const sourcePathKey = sourcePaths.join("\n");
  useEffect(() => {
    let cancelled = false;
    async function loadSource() {
      if (!mr.id || !sourcePaths.length) return;
      setSourceLoading(true);
      const nextPatchByPath: Record<string, string> = {};
      try {
        const files = await api<{ items: MrChangedFile[] }>(`/api/vcs/${projectId}/merge-requests/${mr.id}/files`);
        for (const file of files.items || []) {
          if (file.filename) nextPatchByPath[file.filename] = file.patch || "";
        }
      } catch {
        // Source file loading below still gives useful context when changed-file metadata is unavailable.
      } finally {
        const nextSourceByPath: Record<string, string> = {};
        await Promise.all(sourcePaths.map(async (filePath) => {
          try {
            const result = await api<{ content: string }>(
              `/api/vcs/${projectId}/merge-requests/${mr.id}/file?path=${encodeURIComponent(filePath)}&sha=${encodeURIComponent(mr.latest_head_sha || "")}`
            );
            nextSourceByPath[filePath] = result.content || "";
          } catch {
            nextSourceByPath[filePath] = "";
          }
        }));
        if (!cancelled) {
          setPatchByPath(nextPatchByPath);
          setSourceByPath(nextSourceByPath);
          setSourceCode(nextSourceByPath[finding.file_path] || "");
          setSourcePatch(nextPatchByPath[finding.file_path] || "");
        }
        if (!cancelled) setSourceLoading(false);
      }
    }
    loadSource();
    return () => {
      cancelled = true;
    };
  }, [finding.id, finding.file_path, mr.id, mr.latest_head_sha, projectId, sourcePathKey]);
  useEffect(() => {
    let cancelled = false;
    async function loadRuleDetails() {
      const ruleIds = primaryRules.filter((rule) => rule !== "未声明具体 rule_id");
      if (!ruleIds.length) {
        setRuleDetails([]);
        return;
      }
      setRuleDetailsLoading(true);
      try {
        const result = await api<{ items: RuleDetail[] }>(
          `/api/projects/${projectId}/rule-details?rule_ids=${encodeURIComponent(ruleIds.join(","))}`
        );
        if (!cancelled) setRuleDetails(result.items || []);
      } catch {
        if (!cancelled) setRuleDetails(ruleIds.map((rule) => ({ rule_id: rule, title: rule, missing: true })));
      } finally {
        if (!cancelled) setRuleDetailsLoading(false);
      }
    }
    loadRuleDetails();
    return () => {
      cancelled = true;
    };
  }, [projectId, ruleKey]);
  const patchProblemLines = sourcePatch ? diffCodeWindow(sourcePatch, finding.line_start || 1, finding.line_end || finding.line_start || 1) : [];
  const problemLines = sourceCode
    ? patchProblemLines.length
      ? patchProblemLines
      : sourceCodeWindow(sourceCode, finding.line_start || 1, finding.line_end || finding.line_start || 1)
    : textCodeLines(finding.evidence || location, finding.line_start || 1);
  const suggestionLines = textCodeLines(suggestedCode || "// 当前 finding 未提供明确代码片段，请重新检视生成建议修改代码。", finding.line_start || 1);
  const evidenceCount = sourceObservations.length || toolProvenance.length;
  const source = findingSource(finding);
  const ruleDetailsById = Object.fromEntries(ruleDetails.map((rule) => [rule.rule_id, rule]));
  const sourceLinesForTarget = (filePath: string, startLine: number, endLine: number, fallback: string) => {
    const patch = patchByPath[filePath] || "";
    const source = sourceByPath[filePath] || "";
    const patchLines = patch ? diffCodeWindow(patch, startLine, endLine) : [];
    if (patchLines.length) return patchLines;
    if (source) return sourceCodeWindow(source, startLine, endLine);
    return textCodeLines(fallback || `${filePath}:${startLine}`, startLine);
  };
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <section className="finding-modal" onClick={(event) => event.stopPropagation()}>
        <header className="finding-modal-header">
          <div className="finding-modal-title">
            <div className="finding-modal-kicker">
              <SeverityBadge severity={finding.severity} />
              <span className={`finding-source-tag ${source.type}`}>{source.label}</span>
              <span>{agentLabel(finding.agent_id)}</span>
              <span>置信度 {finding.confidence.toFixed(2)}</span>
              {finding.publish_state && <span>{finding.publish_state}</span>}
            </div>
            <strong>{finding.title}</strong>
            <p>
              <span title={location}>{location}</span>
              <em>{primaryRules.slice(0, 3).join(" / ")}</em>
              {primaryRules.length > 3 && <em>+{primaryRules.length - 3}</em>}
            </p>
          </div>
        </header>

        <div className="finding-core-stack">
          <section className="finding-core-card">
            <h3>问题描述</h3>
            <p>{finding.problem_description || "暂无问题描述。"}</p>
          </section>
          <section className="finding-core-card fix">
            <h3>修复建议</h3>
            <p>{finding.recommendation || "暂无修复建议。"}</p>
          </section>
        </div>

        <div className="finding-detail-section finding-code-stack">
          <h3>问题代码</h3>
          <GithubCodeBlock
            filePath={finding.file_path}
            label={sourceLoading ? "正在加载源代码" : "源问题代码"}
            location={location}
            lines={problemLines}
            highlightStart={finding.line_start || undefined}
            highlightEnd={finding.line_end || finding.line_start || undefined}
          />
        </div>

        <div className="finding-detail-section finding-code-stack">
          <h3>建议修复代码</h3>
          <GithubCodeBlock
            filePath={finding.file_path}
            label="建议代码"
            location={location}
            lines={suggestionLines}
            mode="suggestion"
          />
        </div>

        <details className="finding-collapsible-card">
          <summary>
            <span>违反规范</span>
            <em>{primaryRules.length} 条</em>
          </summary>
          <div className="finding-detail-section finding-rule-section">
            <div className="rule-detail-list">
              {primaryRules.map((rule) => (
                <RuleDetailCard
                  key={rule}
                  ruleId={rule}
                  detail={ruleDetailsById[rule]}
                  loading={ruleDetailsLoading}
                />
              ))}
            </div>
            {skippedRules.length > 0 && <small>已检查未命中：{skippedRules.join(", ")}</small>}
          </div>
        </details>

        <details className="finding-collapsible-card">
          <summary>
            <span>质量追溯</span>
            <em>{evidenceCount} 条证据</em>
          </summary>
          <div className="finding-detail-section finding-trace-section">
            <dl className="trace-list">
              <div>
                <dt>专家</dt>
                <dd>{agentLabel(String(qualityTrace.agent_id || finding.agent_id))}</dd>
              </div>
              <div>
                <dt>定位</dt>
                <dd>{formatTraceLocation(traceLocation) || location}</dd>
              </div>
              <div>
                <dt>来源</dt>
                <dd>{source.label}</dd>
              </div>
              <div>
                <dt>去重指纹</dt>
                <dd>{String(qualityTrace.dedupe_hash || finding.id)}</dd>
              </div>
            </dl>
          </div>
        </details>

        <details className="finding-collapsible-card">
          <summary>
            <span>工具证据</span>
            <em>{sourceObservations.length || 0} 条</em>
          </summary>
          <div className="finding-detail-section">
            {sourceObservations.length ? (
              <div className="tool-evidence-list">
                {sourceObservations.map((item, index) => (
                  <article key={`${String(item.tool_name || "tool")}-${index}`}>
                    <div>
                      <strong>{String(item.tool_name || "unknown_tool")}</strong>
                      {item.rule_id !== undefined && item.rule_id !== null && <span>{String(item.rule_id)}</span>}
                      {item.confidence !== undefined && item.confidence !== null && <em>{Number(item.confidence).toFixed(2)}</em>}
                    </div>
                    <p>{String(item.message || "工具命中候选问题")}</p>
                    <small>{formatObservationLocation(item)}</small>
                    {observationFilePath(item) && (
                      <GithubCodeBlock
                        filePath={observationFilePath(item)}
                        label="工具命中源码"
                        location={formatObservationLocation(item)}
                        lines={sourceLinesForTarget(
                          observationFilePath(item),
                          observationLineStart(item),
                          observationLineEnd(item),
                          String(item.evidence || item.message || "工具命中候选问题")
                        )}
                        highlightStart={observationLineStart(item)}
                        highlightEnd={observationLineEnd(item)}
                      />
                    )}
                  </article>
                ))}
              </div>
            ) : (
              <small>该问题由专家直接提出，当前未匹配到静态工具证据。</small>
            )}
            {toolProvenance.length > sourceObservations.length && <small>同时记录了 {toolProvenance.length} 条 provenance 元数据。</small>}
          </div>
        </details>
      </section>
    </div>
  );
}

function RuleDetailCard({ ruleId, detail, loading }: { ruleId: string; detail?: RuleDetail; loading: boolean }) {
  const sections = detail?.sections || {};
  const preferredSections = ["规范说明", "检查点", "如何检查", "反例", "正例", "说明"];
  const visibleSections = preferredSections
    .map((name) => [name, sections[name]] as [string, string | undefined])
    .filter(([, value]) => value && value.trim());
  return (
    <article className={`rule-detail-card ${detail?.missing ? "missing" : ""}`}>
      <header>
        <div>
          <strong>{ruleId}</strong>
          <span>{loading ? "正在加载规范详情..." : (detail?.document_name || "项目规范")}</span>
        </div>
        {detail?.version && <em>{detail.version}</em>}
      </header>
      <h4>{detail?.title || ruleId}</h4>
      {detail?.missing && <p>当前项目绑定的规范文档中未找到该 rule_id 的详细说明。</p>}
      {!detail?.missing && visibleSections.length > 0 && (
        <div className="rule-detail-sections">
          {visibleSections.map(([name, value]) => (
            <section key={name}>
              <span>{name}</span>
              <p>{value}</p>
            </section>
          ))}
        </div>
      )}
      {!detail?.missing && !visibleSections.length && detail?.raw_excerpt && <p>{detail.raw_excerpt}</p>}
    </article>
  );
}

function GithubCodeBlock({
  filePath,
  label,
  location,
  lines,
  highlightStart,
  highlightEnd,
  mode = "source"
}: {
  filePath: string;
  label: string;
  location?: string;
  lines: ParsedDiffLine[];
  highlightStart?: number;
  highlightEnd?: number;
  mode?: "source" | "suggestion" | "diff";
}) {
  return (
    <div className="code-snippet github-code">
      <div className="code-snippet-toolbar">
        <span>{label}</span>
        {location && <em title={location}>{location}</em>}
        <strong>{languageLabel(filePath)}</strong>
      </div>
      <div className="github-code-table">
        {lines.map((line, index) => {
          const displayLine = line.kind === "del" ? line.oldLine : line.newLine;
          const highlighted = Boolean(
            highlightStart &&
            displayLine &&
            displayLine >= highlightStart &&
            displayLine <= (highlightEnd || highlightStart)
          );
          const marker = line.kind === "add" || mode === "suggestion" ? "+" : line.kind === "del" ? "-" : line.kind === "meta" ? "@@" : "";
          return (
            <div className={`github-code-line ${line.kind} ${highlighted ? "highlight" : ""} ${mode}`} key={`${displayLine ?? "meta"}-${index}`}>
              <span className="old-no">{line.oldLine ?? ""}</span>
              <span className="new-no">{line.newLine ?? ""}</span>
              <span className="diff-marker" aria-label={marker ? `${marker} 变更行` : "上下文行"}>{marker}</span>
              <code>{line.content || " "}</code>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function observationFilePath(item: Record<string, unknown>) {
  return String(item.file_path || item.path || item.filename || "").trim();
}

function observationLineStart(item: Record<string, unknown>) {
  const value = Number(item.line_start || item.start_line || item.line || 1);
  return Number.isFinite(value) && value > 0 ? value : 1;
}

function observationLineEnd(item: Record<string, unknown>) {
  const value = Number(item.line_end || item.end_line || observationLineStart(item));
  return Number.isFinite(value) && value > 0 ? value : observationLineStart(item);
}

function ToolResultsPanel({ detail, onOpenFinding }: { detail: Detail; onOpenFinding: (finding: Finding) => void }) {
  const [activeObservation, setActiveObservation] = useState<Record<string, unknown> | null>(null);
  const toolCalls = detail.session_logs?.tool_calls || [];
  const observations = detail.tool_observations || [];
  const observationsByTool = observations.reduce<Record<string, Array<Record<string, unknown>>>>((acc, item) => {
    const key = String(item.tool_name || "unknown_tool");
    acc[key] = [...(acc[key] || []), item];
    return acc;
  }, {});
  const staticCalls = toolCalls.filter((row) => String(row.tool_name || "").startsWith("static."));
  const openObservation = (row: Record<string, unknown>) => {
    const matchedFinding = findFindingForObservation(detail.findings, row);
    if (matchedFinding) {
      onOpenFinding(matchedFinding);
      return;
    }
    setActiveObservation(row);
  };
  return (
    <>
      <div className="tool-results-panel">
        {staticCalls.map((call, index) => {
          const toolName = String(call.tool_name || "static.tool");
          const rows = observationsByTool[toolName.replace(/^static\./, "")] || observationsByTool[toolName] || [];
          const outputRef = safeJson(String(call.output_ref_json || "{}"));
          return (
            <section className="tool-result-card" key={`${toolName}-${index}`}>
              <header>
                <div>
                  <strong>{toolName}</strong>
                  <span>{String(call.tool_version || "unknown version")}</span>
                </div>
                <em className={`tool-run-status ${String(call.status || "").replace(/[^a-z0-9_-]/gi, "_")}`}>{String(call.status || "--")}</em>
              </header>
              <div className="tool-result-meta">
                <p><span>耗时</span><strong>{formatDurationMs(call.duration_ms)}</strong></p>
                <p><span>命中</span><strong>{rows.length}</strong></p>
                <p><span>Artifact</span><strong title={String(outputRef.path || outputRef.artifact || "--")}>{shortPath(String(outputRef.path || outputRef.artifact || "--"))}</strong></p>
              </div>
              <p className="tool-output-summary">{String(call.output_summary || "工具已执行，暂无输出摘要。")}</p>
              <div className="tool-observation-table">
                {rows.slice(0, 12).map((row, rowIndex) => (
                  <button className="tool-observation-row" type="button" key={rowIndex} onClick={() => openObservation(row)}>
                    <strong>{String(row.rule_id || "--")}</strong>
                    <span>{formatObservationLocation(row)}</span>
                    <em>{Number(row.confidence || 0).toFixed(2)}</em>
                    <p>{String(row.message || "--")}</p>
                  </button>
                ))}
                {!rows.length && <div className="static-tool-empty">该工具本次没有产生可归一化检测结果。</div>}
              </div>
            </section>
          );
        })}
        {!staticCalls.length && observations.length > 0 && (
          <section className="tool-result-card">
            <header>
              <div>
                <strong>tool_observations</strong>
                <span>归一化静态工具检测结果</span>
              </div>
              <em className="tool-run-status completed">completed</em>
            </header>
            <div className="tool-observation-table">
              {observations.slice(0, 30).map((row, rowIndex) => (
                <button className="tool-observation-row" type="button" key={rowIndex} onClick={() => openObservation(row)}>
                  <strong>{String(row.rule_id || "--")}</strong>
                  <span>{formatObservationLocation(row)}</span>
                  <em>{Number(row.confidence || 0).toFixed(2)}</em>
                  <p>{String(row.message || "--")}</p>
                </button>
              ))}
            </div>
          </section>
        )}
        {!staticCalls.length && !observations.length && <div className="empty-finding">暂无静态工具调用记录。</div>}
      </div>
      {activeObservation && <ToolObservationModal observation={activeObservation} onClose={() => setActiveObservation(null)} />}
    </>
  );
}

function findFindingForObservation(findings: Finding[], observation: Record<string, unknown>) {
  const obsPath = String(observation.file_path || "");
  const obsRule = String(observation.rule_id || "");
  const obsLine = Number(observation.line_start || 0);
  return findings.find((finding) => {
    const sameFile = !obsPath || finding.file_path === obsPath || finding.file_path.endsWith(obsPath) || obsPath.endsWith(finding.file_path);
    const sameLine = !obsLine || !finding.line_start || Math.abs(Number(finding.line_start) - obsLine) <= 5;
    if (!sameFile || !sameLine) return false;
    const text = `${finding.covered_rules_json || ""} ${finding.tool_provenance_json || ""} ${finding.source_observations_json || ""}`;
    return !obsRule || text.includes(obsRule) || text.includes(canonicalDisplayRule(obsRule));
  });
}

function canonicalDisplayRule(value: string) {
  return value.includes(".prescan.") ? value.split(".prescan.", 2)[1] : value;
}

function ToolObservationModal({ observation, onClose }: { observation: Record<string, unknown>; onClose: () => void }) {
  const location = formatObservationLocation(observation);
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <section className="tool-observation-modal" onClick={(event) => event.stopPropagation()}>
        <header>
          <div>
            <strong>{String(observation.tool_name || "静态工具")} · {String(observation.rule_id || "--")}</strong>
            <span>{location}</span>
          </div>
          <em>{Number(observation.confidence || 0).toFixed(2)}</em>
        </header>
        <div className="tool-observation-meta-grid">
          <article>
            <span>工具</span>
            <strong>{String(observation.tool_name || "--")}</strong>
          </article>
          <article>
            <span>规则</span>
            <strong>{String(observation.rule_id || "--")}</strong>
          </article>
          <article>
            <span>位置</span>
            <strong>{location}</strong>
          </article>
          <article>
            <span>置信度</span>
            <strong>{Number(observation.confidence || 0).toFixed(2)}</strong>
          </article>
        </div>
        <div className="finding-detail-section">
          <h3>检测结果</h3>
          <p>{String(observation.message || observation.title || "该工具命中候选问题。")}</p>
        </div>
        <div className="finding-detail-section">
          <h3>原始记录</h3>
          <pre className="tool-observation-json">{JSON.stringify(observation, null, 2)}</pre>
        </div>
      </section>
    </div>
  );
}

function MrPreviewModal({
  detail,
  files,
  loading,
  onClose
}: {
  detail: Detail;
  files: MrChangedFile[];
  loading: boolean;
  onClose: () => void;
}) {
  const [activeFile, setActiveFile] = useState("");
  const safeFiles = useMemo(() => normalizeMrChangedFiles(files), [files]);
  useEffect(() => {
    if (!safeFiles.length) {
      if (activeFile) setActiveFile("");
      return;
    }
    if (!activeFile || !safeFiles.some((file) => file.filename === activeFile)) {
      setActiveFile(safeFiles[0].filename);
    }
  }, [activeFile, safeFiles]);
  const current = safeFiles.find((file) => file.filename === activeFile) || safeFiles[0] || null;
  const tree = buildFileTree(safeFiles);
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <section className="mr-preview-modal" onClick={(event) => event.stopPropagation()}>
        <header>
          <div>
            <strong>!{detail.mr.number} {detail.mr.title}</strong>
            <span>{detail.mr.repository_name} · {detail.mr.source_branch} → {detail.mr.target_branch} · {detail.mr.author}</span>
          </div>
          <StatusBadge status={effectiveReviewStatus(detail)} />
        </header>
        <div className="mr-preview-body">
          <aside className="mr-file-tree">
            <strong>变更文件</strong>
            {loading && <p>正在加载 diff...</p>}
            {!loading && !tree.length && <p>暂无变更文件。可能是空提交、平台未返回文件列表，或该 MR 只有元数据变化。</p>}
            {!loading && tree.map((entry) => entry.kind === "directory" ? (
              <div
                key={entry.key}
                className={`mr-file-tree-node directory ${current?.filename?.startsWith(`${entry.path}/`) ? "contains-active" : ""}`}
                style={{ paddingLeft: `${10 + entry.depth * 14}px` }}
                title={entry.path}
              >
                <Folder size={14} />
                <span>{entry.name}</span>
              </div>
            ) : (
              <button
                key={entry.key}
                type="button"
                className={`mr-file-tree-node file ${current?.filename === entry.path ? "active" : ""}`}
                style={{ paddingLeft: `${10 + entry.depth * 14}px` }}
                onClick={() => setActiveFile(entry.path)}
                title={entry.path}
              >
                <FileCode2 size={14} />
                <span>
                  <strong>{entry.name}</strong>
                  <small>{entry.path}</small>
                </span>
                <em>{entry.status}</em>
              </button>
            ))}
          </aside>
          <main className="mr-diff-view">
            {current ? (
              <>
                <div className="mr-diff-head">
                  <div>
                    <strong title={current.filename}>{basename(current.filename)}</strong>
                    <small title={current.filename}>{current.filename}</small>
                  </div>
                  <span>+{current.additions || 0} / -{current.deletions || 0}</span>
                </div>
                <GithubCodeBlock
                  filePath={current.filename}
                  label="Diff"
                  location={current.filename}
                  lines={parseUnifiedPatch(current.patch || "")}
                  mode="diff"
                />
              </>
            ) : (
              <div className="empty-finding">暂无 diff 文件。</div>
            )}
          </main>
        </div>
      </section>
    </div>
  );
}

function TracePreview({ trace }: { trace: Array<Record<string, unknown>> }) {
  if (!trace.length) return null;
  return (
    <details className="trace-preview">
      <summary>
        <SlidersHorizontal size={16} />
        检视过程 · {trace.length} 条记录
      </summary>
      <div>
        {trace.slice(0, 8).map((item, index) => (
          <p key={index}>
            <strong>{String(item.span_key || item.event_type || "trace")}</strong>
            <span>{String(item.summary || item.status || "执行记录")}</span>
          </p>
        ))}
      </div>
    </details>
  );
}

function agentLabel(agentId: string) {
  const map: Record<string, string> = {
    performance_agent: "Performance Agent",
    security_agent: "Security Agent",
    coding_agent: "General Coding Agent",
    ddd_agent: "DDD Design Agent",
    frontend_agent: "Frontend Agent",
    test_agent: "Test Agent",
    redis_agent: "Redis Agent",
    backend_agent: "Backend Agent"
  };
  return map[agentId] || agentId;
}

function estimateDuration(detail: Detail) {
  const run = detail.runs[0];
  const started = String(run?.started_at || "");
  const completed = String(run?.completed_at || "");
  if (!started || !completed) return detail.runs.length ? "进行中" : "--";
  const start = new Date(started.replace(" ", "T") + "Z").getTime();
  const end = new Date(completed.replace(" ", "T") + "Z").getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "<1m";
  const seconds = Math.max(1, Math.round((end - start) / 1000));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function safeJson(value: string) {
  try {
    return JSON.parse(value || "{}") as Record<string, unknown>;
  } catch {
    return {};
  }
}


function parseJsonArray(value: string | undefined) {
  try {
    const parsed = JSON.parse(value || "[]");
    return Array.isArray(parsed) ? parsed.map((item) => String(item)) : [];
  } catch {
    return [];
  }
}

function parseJsonObjectArray(value: string | undefined) {
  try {
    const parsed = JSON.parse(value || "[]");
    return Array.isArray(parsed) ? parsed.filter((item) => item && typeof item === "object") as Array<Record<string, unknown>> : [];
  } catch {
    return [];
  }
}

function formatTraceLocation(location: Record<string, unknown> | undefined) {
  if (!location) return "";
  const file = String(location.file_path || "");
  if (!file) return "";
  const start = location.line_start ? Number(location.line_start) : null;
  const end = location.line_end ? Number(location.line_end) : null;
  if (!start) return file;
  if (end && end !== start) return `${file}:${start}-${end}`;
  return `${file}:${start}`;
}

function formatObservationLocation(item: Record<string, unknown>) {
  return formatTraceLocation({
    file_path: item.file_path,
    line_start: item.line_start,
    line_end: item.line_end,
  }) || "--";
}

function extractSuggestedCode(value: string) {
  const fence = value.match(/```[a-zA-Z0-9_-]*\n([\s\S]*?)```/);
  return fence ? fence[1].trim() : "";
}

function languageLabel(filePath: string) {
  const extension = filePath.split(".").pop()?.toLowerCase();
  const map: Record<string, string> = {
    java: "Java",
    kt: "Kotlin",
    js: "JavaScript",
    jsx: "React JSX",
    ts: "TypeScript",
    tsx: "React TSX",
    py: "Python",
    sql: "SQL",
    xml: "XML",
    yml: "YAML",
    yaml: "YAML",
    json: "JSON",
    css: "CSS",
    scss: "SCSS",
    html: "HTML",
    md: "Markdown"
  };
  return map[extension || ""] || "Code";
}

createRoot(document.getElementById("root")!).render(<App />);
