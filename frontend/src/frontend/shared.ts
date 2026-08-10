import { resolveApiBase, type ApiBaseConfig } from "./apiRouting";
import {
  isStandardSkillAssetPath,
  normalizeSkillBundleAssetPath,
  skillRootNameFromFiles,
  uploadRelativePath
} from "./skillUploadPaths";

export const API_BASES: ApiBaseConfig = {
  legacyBase: import.meta.env.VITE_API_BASE || "",
  commonBase: import.meta.env.VITE_COMMON_API_BASE,
  mrBase: import.meta.env.VITE_MR_API_BASE
};
export const DEFAULT_PROJECT_ID = "project_default";
export const DEFAULT_WORKSPACE_MESSAGE = "请选择项目进入 MR 工作台";
export const SOURCE_CONTEXT_RADIUS = 5;
export type ViewKey = "mr" | "full" | "issues" | "rules" | "agents" | "repos" | "policy" | "users" | "tools" | "queue" | "personal" | "settings" | "system";
export type RouteScreen = "login" | "projects" | "workspace";
export type WorkspaceRouteState = {
  screen: RouteScreen;
  projectId: string;
  view: ViewKey;
  mrId: string | null;
};

export let authToken = typeof window !== "undefined" ? window.localStorage.getItem("jolt_auth_token") : null;
export const WORKSPACE_ROUTE_KEY = "jolt_workspace_route";
export const VIEW_KEY_SET = new Set<ViewKey>(["mr", "full", "issues", "rules", "agents", "repos", "policy", "users", "tools", "queue", "personal", "settings", "system"]);

export function setApiToken(token: string | null) {
  authToken = token;
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem("jolt_auth_token", token);
  else window.localStorage.removeItem("jolt_auth_token");
}

export function normalizeViewKey(value: unknown): ViewKey {
  const view = String(value || "mr");
  return VIEW_KEY_SET.has(view as ViewKey) ? view as ViewKey : "mr";
}

export function readWorkspaceRoute(): WorkspaceRouteState {
  const fallback: WorkspaceRouteState = { screen: "login", projectId: DEFAULT_PROJECT_ID, view: "mr", mrId: null };
  if (typeof window === "undefined") return fallback;
  let stored: Partial<WorkspaceRouteState> = {};
  try {
    stored = JSON.parse(window.localStorage.getItem(WORKSPACE_ROUTE_KEY) || "{}") as Partial<WorkspaceRouteState>;
  } catch {
    stored = {};
  }
  const pathParts = window.location.pathname.split("/").filter(Boolean);
  const params = new URLSearchParams(window.location.search);
  if (pathParts[0] === "login") {
    return { screen: "login", projectId: stored.projectId || fallback.projectId, view: normalizeViewKey(stored.view), mrId: null };
  }
  if (pathParts[0] === "projects" && !pathParts[1]) {
    return { screen: "projects", projectId: stored.projectId || fallback.projectId, view: normalizeViewKey(stored.view), mrId: null };
  }
  if (pathParts[0] === "projects" && pathParts[1]) {
    return {
      screen: "workspace",
      projectId: decodeURIComponent(pathParts[1]),
      view: normalizeViewKey(pathParts[2] === "review" ? "mr" : pathParts[2] || stored.view),
      mrId: params.get("mr") || stored.mrId || null
    };
  }
  return {
    screen: stored.screen || fallback.screen,
    projectId: stored.projectId || fallback.projectId,
    view: normalizeViewKey(stored.view),
    mrId: stored.mrId || null
  };
}

export function writeWorkspaceRoute(state: WorkspaceRouteState) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(WORKSPACE_ROUTE_KEY, JSON.stringify(state));
  let nextPath = "/login";
  let nextSearch = "";
  if (state.screen === "projects") {
    nextPath = "/projects";
  }
  if (state.screen === "workspace") {
    const viewPath = state.view === "mr" ? "review" : state.view;
    nextPath = `/projects/${encodeURIComponent(state.projectId || DEFAULT_PROJECT_ID)}/${viewPath}`;
    if (state.mrId) {
      const params = new URLSearchParams();
      params.set("mr", state.mrId);
      nextSearch = `?${params.toString()}`;
    }
  }
  if (window.location.pathname !== nextPath || window.location.search !== nextSearch || window.location.hash) {
    window.history.replaceState(null, "", `${nextPath}${nextSearch}`);
  }
}

export type User = {
  id: string;
  username: string;
  display_name: string;
  email?: string | null;
  global_role?: string;
  status?: string;
};

export type Project = {
  id: string;
  name: string;
  description?: string;
  role?: string;
  join_request_status?: string | null;
  requested_role?: string | null;
};

export type Repo = {
  id: string;
  provider: string;
  external_repo_id: string;
  name: string;
  default_branch: string;
  status: string;
};

export type MergeRequest = {
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
  review_started_at?: string | null;
  finding_count: number;
  latest_run_status?: string;
  queue_blocked_by_project?: boolean;
  queue_blocked_reason?: string;
  added_lines?: number | null;
  max_added_lines_per_mr?: number;
  size_policy_state?: "unknown" | "within_limit" | "over_limit";
  size_policy_message?: string;
  active_project_review?: {
    job_id?: string;
    status?: string;
    merge_request_id?: string;
    number?: number;
    title?: string;
  } | null;
};

export type Finding = {
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
  evidence_score_json?: string;
  selected: number;
  publish_state: string;
  lifecycle_state: string;
};

export type MrActionState = "start" | "pause" | "stop" | "rerun";

export type RuleDetail = {
  rule_id: string;
  title: string;
  document_name?: string;
  version?: string;
  sections?: Record<string, string>;
  raw_excerpt?: string;
  missing?: boolean;
};

export type Detail = {
  mr: MergeRequest & { external_repo_id: string };
  diagnostics_visible?: boolean;
  has_review_run?: boolean;
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
    skill_calls?: Array<Record<string, unknown>>;
    artifacts: Array<Record<string, unknown>>;
  };
  quality?: Record<string, unknown>;
};

export type MrChangedFile = {
  filename: string;
  status?: string;
  additions?: number;
  deletions?: number;
  patch?: string;
  previous_filename?: string;
};

export type ParsedDiffLine = {
  kind: "context" | "add" | "del" | "meta";
  oldLine: number | null;
  newLine: number | null;
  content: string;
};

export type StaticToolAvailabilityItem = {
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

export type StaticToolAvailability = {
  platform: string;
  os: string;
  path_delimiter: string;
  checked_at: string;
  total: number;
  available_count: number;
  missing_count: number;
  items: StaticToolAvailabilityItem[];
};

export type LlmSettingsForm = {
  default_provider: string;
  default_base_url: string;
  default_model: string;
  default_api_key: string;
  default_api_key_has_value: boolean;
  default_api_key_masked: string;
  request_timeout_seconds: string;
  max_output_tokens: string;
  enable_stream: boolean;
};

export type VcsTokenForm = {
  codehub_token: string;
  codehub_token_has_value?: boolean;
  codehub_token_masked?: string;
};

export type ProjectVcsSettingsForm = {
  codehub_token: string;
  codehub_token_env: string;
  codehub_endpoint: string;
  github_token: string;
  github_token_env: string;
  github_endpoint: string;
};

export type StorageSettingsForm = {
  postgres_url: string;
  postgres_user: string;
  postgres_password: string;
  postgres_password_has_value?: boolean;
  postgres_password_masked?: string;
};

export type ReviewSettingsForm = {
  effort: string;
  max_findings_per_mr: string;
  max_added_lines_per_mr: string;
  min_confidence: string;
  enable_full_repo_context: boolean;
};

export type BudgetEffortForm = {
  max_llm_calls: string;
  max_wall_seconds: string;
  max_output_tokens: string;
  max_findings: string;
};

export type BudgetSettingsForm = {
  standard: BudgetEffortForm;
  deep: BudgetEffortForm;
};

export type AgentSettingsForm = {
  max_parallel_agents: string;
  enable_llm_routing: boolean;
  require_rule_coverage: boolean;
  default_max_tool_calls: string;
};

export type ToolSettingsForm = {
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

export type StaticToolSwitch = {
  key: string;
  availabilityName: string;
  displayName: string;
  category: string;
  requiredFor: string;
};

export const STATIC_TOOL_SWITCHES: StaticToolSwitch[] = [
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

export const DEFAULT_STATIC_TOOL_ENABLED = Object.fromEntries(STATIC_TOOL_SWITCHES.map((tool) => [tool.key, true]));

export type QueueSettingsForm = {
  poll_interval_seconds: string;
  max_concurrency: string;
  max_attempts: string;
  heartbeat_timeout_seconds: string;
};

export type PublishSettingsForm = {
  require_manual_confirmation: boolean;
  dry_run: boolean;
  allowed_severities: string;
};

export type DataSettingsForm = {
  prompt_retention: string;
  diff_max_lines_to_llm: string;
  sensitive_paths: string;
  fallback_on_violation: string;
};

export type AgentBindingDetail = {
  kind: "rule" | "skill" | "asset";
  title: string;
  subtitle: string;
  content: string;
  metadata: Array<[string, string]>;
  assets?: Array<{ path: string; type: string; executable: boolean }>;
  bindingId?: string;
  skillKey?: string;
};

export type AgentBindingEditorOptions = {
  ruleDocs: Record<string, unknown>[];
  ruleBindings: Record<string, unknown>[];
  customSkills: Record<string, unknown>[];
  skillAssets: Record<string, unknown>[];
  skillBindings: Record<string, unknown>[];
  toolBindings: Record<string, unknown>[];
  staticToolAvailability: StaticToolAvailability | null;
};

export type LlmTestState = {
  status: "idle" | "testing" | "ok" | "failed";
  message: string;
};

export type FormActionState = {
  status: "idle" | "saving" | "ok" | "failed";
  message: string;
};

export type SuccessNotice = {
  title: string;
  message: string;
  detail?: string;
};

export type PublishResultNotice = {
  status: "success" | "failed";
  title: string;
  message: string;
  publishedCount: number;
  requestedCount: number;
  skippedCount?: number;
  detail?: string;
};

export type PublishApiResult = {
  published_count: number;
  dry_run: boolean;
  skipped_count?: number;
  skipped_finding_ids?: string[];
  message?: string;
};

export type MarkdownExportResponse = {
  filename: string;
  content_type: string;
  content: string;
};

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${resolveApiBase(path, API_BASES)}${path}`, {
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

export function listItems<T>(value: T[] | { items?: T[] } | null | undefined): T[] {
  if (Array.isArray(value)) return value;
  return Array.isArray(value?.items) ? value.items : [];
}

export function readUploadText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("文件读取失败"));
    reader.readAsText(file, "utf-8");
  });
}

export function readableFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 102.4) / 10} KB`;
  return `${Math.round(bytes / 1024 / 102.4) / 10} MB`;
}

export async function buildSkillBundleAssets(files: File[]) {
  const filtered = files.filter((file) => file.size >= 0 && !uploadRelativePath(file).split("/").some((segment) => segment === ".DS_Store"));
  const assets = filtered
    .map((file) => ({ file, assetPath: normalizeSkillBundleAssetPath(file) }))
    .filter((item) => item.assetPath && !item.assetPath.includes("..") && isStandardSkillAssetPath(item.assetPath));
  return Promise.all(
    assets.map(async (asset) => ({
      file: asset.file,
      asset_path: asset.assetPath,
      content: await readUploadText(asset.file),
      executable: asset.assetPath.startsWith("scripts/")
    }))
  );
}

export async function validateSkillBundle(input: {
  projectId: string;
  skillName: string;
  skillKey: string;
  content?: string;
  files?: File[];
  assets?: Array<{ asset_path: string; content: string }>;
}) {
  const assets = input.files?.length
    ? (await buildSkillBundleAssets(input.files)).map((asset) => ({ asset_path: asset.asset_path, content: asset.content }))
    : [{ asset_path: "SKILL.md", content: input.content || "" }, ...(input.assets ?? [])];
  return api<Record<string, unknown>>(`/api/projects/${input.projectId}/custom-skills/validate`, {
    method: "POST",
    body: JSON.stringify({
      skill_key: input.skillKey.trim() || input.skillName.trim(),
      name: input.skillName.trim(),
      content: input.content || "",
      assets
    })
  });
}

export async function uploadSkillBundleToProject(input: {
  projectId: string;
  agentKey: string;
  skillName: string;
  skillKey: string;
  files: File[];
  version?: string;
  status?: "draft" | "active";
}) {
  if (!input.files.length) throw new Error("请选择标准 Skill 文件夹");
  const validation = await validateSkillBundle({ projectId: input.projectId, skillName: input.skillName, skillKey: input.skillKey, files: input.files });
  if (!validation.ok) throw new Error(`Skill 校验未通过：${JSON.stringify(validation.failures || [], null, 2)}`);
  const assets = await buildSkillBundleAssets(input.files);
  const skillMd = assets.find((item) => item.asset_path === "SKILL.md");
  if (!skillMd) throw new Error("Skill 文件夹必须包含 SKILL.md");
  const skillContent = skillMd.content;
  const rootName = skillRootNameFromFiles(input.files);
  const skillName = input.skillName.trim() || rootName || "项目自定义 Skill";
  const skillKey = input.skillKey.trim() || rootName || skillName;
  const version = input.version?.trim() || "v1";
  const status = "draft";
  const skill = await api<Record<string, unknown>>(`/api/projects/${input.projectId}/custom-skills`, {
    method: "POST",
    body: JSON.stringify({
      skill_key: skillKey,
      name: skillName,
      description: "项目级标准 Skill Bundle",
      content: skillContent,
      version,
      status,
      assets
    })
  });
  const createdSkillKey = String(skill.skill_key || skillKey);
  for (const asset of assets) {
    await api(`/api/projects/${input.projectId}/custom-skill-assets`, {
      method: "POST",
      body: JSON.stringify({
        skill_key: createdSkillKey,
        version,
        asset_path: asset.asset_path,
        content: asset.content,
        executable: asset.executable
      })
    });
  }
  if (input.agentKey) {
    await api(`/api/projects/${input.projectId}/expert-skill-bindings`, {
      method: "POST",
      body: JSON.stringify({ agent_key: input.agentKey, skill_key: createdSkillKey, priority: 100, enabled: true })
    });
  }
  return { skillKey: createdSkillKey, assetCount: assets.length, validation };
}

export function normalizeMrChangedFiles(value: unknown): MrChangedFile[] {
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

export function splitCsv(value: string) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

export function clampLlmTimeout(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(1, Math.min(600, parsed)) : 120;
}

export function clampLlmOutputTokens(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(1024, Math.min(131072, parsed)) : 8192;
}

export function positiveNumber(value: string, fallback: number, max = Number.MAX_SAFE_INTEGER) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, Math.min(max, parsed)) : fallback;
}

export function csvValue(value: unknown) {
  if (Array.isArray(value)) return value.map(String).join(", ");
  return typeof value === "string" ? value : "";
}

export function recordValue(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value ? value as Record<string, unknown> : {};
}

export function compactMetadata(items: Array<[string, unknown]>): Array<[string, string]> {
  return items.reduce<Array<[string, string]>>((result, [label, value]) => {
    if (value !== undefined && value !== null && value !== "") result.push([label, String(value)]);
    return result;
  }, []);
}

export function skillAssetKind(asset: Record<string, unknown>) {
  const type = String(asset.asset_type || "");
  const path = String(asset.asset_path || "");
  if (type) return type;
  if (path === "SKILL.md") return "skill";
  if (path.startsWith("references/")) return "reference";
  if (path.startsWith("scripts/")) return "script";
  if (path.startsWith("assets/")) return "asset";
  return "asset";
}

export function skillAssetSummary(assets: Record<string, unknown>[]) {
  const counts = assets.reduce<Record<string, number>>((result, asset) => {
    const kind = skillAssetKind(asset);
    result[kind] = (result[kind] || 0) + 1;
    return result;
  }, {});
  const parts = [
    ["skill", "入口"],
    ["reference", "参考"],
    ["script", "脚本"],
    ["asset", "资源"]
  ].flatMap(([key, label]) => counts[key] ? [`${label} ${counts[key]}`] : []);
  return parts.length ? `${assets.length} 个文件 · ${parts.join(" / ")}` : "0 个文件";
}

export function skillAssetManifest(assets: Record<string, unknown>[]) {
  if (!assets.length) return "暂无 bundle 文件";
  return assets
    .map((asset) => {
      const path = String(asset.asset_path || "未命名资源");
      const kind = skillAssetKind(asset);
      const executable = asset.executable ? " · 可执行" : "";
      return `- ${path} (${kind}${executable})`;
    })
    .join("\n");
}

export function skillAssetPathPreview(assets: Array<Record<string, unknown> | { path: string }>) {
  if (!assets.length) return "";
  const paths = assets.map((asset) => String("asset_path" in asset ? asset.asset_path || "未命名资源" : asset.path || "未命名资源"));
  const visible = paths.slice(0, 5).join(" / ");
  return paths.length > 5 ? `${visible} / +${paths.length - 5}` : visible;
}

export function skillBundleContent(skill: Record<string, unknown>, assets: Record<string, unknown>[]) {
  if (!assets.length) return String(skill.content || "暂无 Skill 内容");
  return assets
    .map((asset) => {
      const path = String(asset.asset_path || "未命名资源");
      const kind = skillAssetKind(asset);
      const content = String(asset.content ?? "");
      return [`## ${path} (${kind})`, content.trim() ? content : "（空文件）"].join("\n\n");
    })
    .join("\n\n---\n\n");
}

export function boolValue(value: unknown, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

export function staticToolPolicyValue(toolPolicy: Record<string, unknown>, staticRunners: Record<string, unknown>, tool: StaticToolSwitch) {
  const enabledTools = Array.isArray(toolPolicy.enabled_tools) ? toolPolicy.enabled_tools.map(String) : [];
  const disabledTools = Array.isArray(toolPolicy.disabled_tools) ? toolPolicy.disabled_tools.map(String) : [];
  const aliases = new Set([tool.key, tool.availabilityName]);
  const runner = recordValue(staticRunners[tool.key] ?? staticRunners[tool.availabilityName]);
  if (disabledTools.some((item) => aliases.has(item))) return false;
  if (enabledTools.length > 0) return enabledTools.some((item) => aliases.has(item));
  return boolValue(runner.enabled, true);
}

export function staticRunnerPayload(toolForm: ToolSettingsForm) {
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

export function statusLabel(status: string) {
  const map: Record<string, string> = {
    queued: "等待检视",
    project_queued: "排队中",
    fetching: "读取变更",
    pre_scanning: "工具检查",
    reviewing: "检视中",
    judging: "整理结果",
    running: "检视中",
    waiting_confirmation: "待确认",
    submitted: "已提交",
    no_issue: "无问题",
    too_large: "MR 过大",
    merged: "已合入",
    closed: "已关闭",
    paused: "已暂停",
    cancelled: "已停止",
    failed: "失败"
  };
  return map[status] || status;
}

export function formatDurationMs(value: unknown) {
  const ms = Number(value || 0);
  if (!Number.isFinite(ms) || ms <= 0) return "0ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)}s`;
}

export function parseBackendTime(value: unknown) {
  const raw = String(value || "").trim();
  if (!raw) return null;
  const normalized = raw.includes("T") ? raw : raw.replace(" ", "T");
  const date = new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(normalized) ? normalized : `${normalized}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value: unknown) {
  const date = parseBackendTime(value);
  if (!date) return "--";
  return date.toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  });
}

export function formatElapsedSeconds(seconds: number) {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const rest = safeSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${rest}s`;
  if (minutes > 0) return `${minutes}m ${rest}s`;
  return `${rest}s`;
}

export const ACTIVE_REVIEW_STATUSES = ["fetching", "pre_scanning", "reviewing", "judging", "running"];
export const TERMINAL_MR_STATUSES = ["merged", "closed"];
export const SYSTEM_AGENT_IDS = new Set(["router_agent", "budget_guard", "summary_agent", "system", "unknown_agent"]);
export const REVIEW_STEPS = [
  { key: "queued", label: "等待开始", description: "任务已提交，正在等待后台处理" },
  { key: "fetching", label: "读取变更", description: "读取 MR 的变更文件和代码内容" },
  { key: "pre_scanning", label: "工具检查", description: "用代码检查工具先找一批确定性问题" },
  { key: "reviewing", label: "AI 专家分析", description: "不同专家按规范分析代码问题" },
  { key: "judging", label: "整理结果", description: "合并重复项，保留证据充分的问题" },
  { key: "done", label: "等待确认", description: "问题已生成，等待你确认后提交到 CodeHub" }
];

export function effectiveReviewStatus(detail: Detail) {
  const latestJobStatus = String(detail.jobs?.[0]?.status || "");
  if (ACTIVE_REVIEW_STATUSES.includes(latestJobStatus)) return latestJobStatus;
  return detail.mr.review_status;
}

export function isTerminalMrStatus(status: string) {
  return TERMINAL_MR_STATUSES.includes(status);
}

export function reviewStepIndex(status: string) {
  if (status === "queued") return 0;
  if (status === "fetching") return 1;
  if (status === "pre_scanning") return 2;
  if (status === "reviewing" || status === "running") return 3;
  if (status === "judging") return 4;
  return 5;
}

export function severityText(severity: string) {
  const map: Record<string, string> = { critical: "严重", high: "高危", medium: "中危", low: "低危" };
  return map[severity] || severity;
}

export function publishStateLabel(state: string) {
  const map: Record<string, string> = {
    pending: "待提交",
    dry_run: "已预览",
    published: "已提交过",
    false_positive: "误报"
  };
  return map[state] || state;
}

export function isAlreadyPublishedFinding(finding: Pick<Finding, "publish_state">) {
  return finding.publish_state === "published";
}

export function severityRank(severity: string) {
  const map: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
  return map[severity] ?? 9;
}

export function sortFindingsBySeverity(findings: Finding[]) {
  return [...findings].sort((left, right) => {
    const severityDiff = severityRank(left.severity) - severityRank(right.severity);
    if (severityDiff !== 0) return severityDiff;
    const confidenceDiff = Number(right.confidence || 0) - Number(left.confidence || 0);
    if (confidenceDiff !== 0) return confidenceDiff;
    return (left.file_path || "").localeCompare(right.file_path || "") || Number(left.line_start || 0) - Number(right.line_start || 0);
  });
}

export type FindingLocationGroup = {
  key: string;
  location: string;
  findings: Finding[];
};

export function groupFindingsByLocation(findings: Finding[]): FindingLocationGroup[] {
  const groups = new Map<string, FindingLocationGroup>();
  for (const finding of findings) {
    const location = formatFindingLocation(finding);
    const existing = groups.get(location);
    if (existing) existing.findings.push(finding);
    else groups.set(location, { key: location, location, findings: [finding] });
  }
  return [...groups.values()];
}

function sharedSafeJson(value: string) {
  try {
    return JSON.parse(value || "{}") as Record<string, unknown>;
  } catch {
    return {};
  }
}

function sharedParseJsonObjectArray(value: string | undefined) {
  try {
    const parsed = JSON.parse(value || "[]");
    return Array.isArray(parsed) ? parsed.filter((item) => item && typeof item === "object") as Array<Record<string, unknown>> : [];
  } catch {
    return [];
  }
}

function sharedAgentLabel(agentId: string) {
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

export function findingSource(finding: Finding) {
  const observations = sharedParseJsonObjectArray(finding.source_observations_json);
  const provenance = sharedParseJsonObjectArray(finding.tool_provenance_json);
  const toolName = [...observations, ...provenance]
    .map((item) => String(item.tool_name || item.tool || item.source || "").trim())
    .find((value) => value && value !== "tool_observation");
  if (observations.length || provenance.some((item) => item.tool_name || item.source === "tool_observation")) {
    return {
      type: "tool" as const,
      label: "工具检出",
      detail: toolName || sharedAgentLabel(finding.agent_id)
    };
  }
  return {
    type: "ai" as const,
    label: "AI 语义检出",
    detail: sharedAgentLabel(finding.agent_id)
  };
}

export function isReviewExpertAgent(agentId: string) {
  const normalized = String(agentId || "").trim();
  if (!normalized || SYSTEM_AGENT_IDS.has(normalized)) return false;
  return normalized.endsWith("_agent") || normalized.includes("_agent_");
}

export function addAgentId(target: Set<string>, value: unknown) {
  const agentId = String(value || "").trim();
  if (isReviewExpertAgent(agentId)) target.add(agentId);
}

export function addAgentIdsFromPayload(target: Set<string>, payload: Record<string, unknown>) {
  const agents = payload.agents;
  if (Array.isArray(agents)) agents.forEach((agent) => addAgentId(target, agent));
  const selectedAgents = payload.selected_agents;
  if (Array.isArray(selectedAgents)) {
    selectedAgents.forEach((agent) => {
      if (typeof agent === "string") addAgentId(target, agent);
      if (agent && typeof agent === "object") addAgentId(target, (agent as Record<string, unknown>).agent_id);
    });
  }
}

export function recordTimestamp(row: Record<string, unknown>) {
  return row.timestamp || row.created_at || row.started_at || row.completed_at || "";
}

export function participatingAgentIds(detail: Detail) {
  const agents = new Set<string>();
  for (const row of detail.trace || []) {
    addAgentId(agents, row.agent_id);
    if (String(row.event_type || "") === "agent_routed") {
      addAgentIdsFromPayload(agents, sharedSafeJson(String(row.payload_json || "{}")));
    }
  }

  for (const run of detail.runs || []) {
    const coverage = sharedSafeJson(String(run.coverage_json || "{}"));
    const coverageAgents = Array.isArray(coverage.agents_executed) ? coverage.agents_executed : [];
    coverageAgents.forEach((agent) => addAgentId(agents, agent));
  }

  const sessionLogs = detail.session_logs;
  [
    ...(sessionLogs?.messages || []),
    ...(sessionLogs?.tool_calls || []),
    ...(sessionLogs?.llm_calls || []),
    ...(sessionLogs?.mcp_calls || [])
  ].forEach((row) => {
    addAgentId(agents, row.agent_id);
    addAgentId(agents, row.from_agent);
    addAgentId(agents, row.to_agent);
  });

  detail.findings.forEach((finding) => addAgentId(agents, finding.agent_id));
  return Array.from(agents).sort();
}

export function riskLevel(score: number) {
  if (score >= 70) return "high";
  if (score >= 35) return "medium";
  return "low";
}

export function shortTime(value: string) {
  const date = parseBackendTime(value);
  if (!date) return value ? value.slice(11, 16) || value : "--";
  return date.toLocaleTimeString("zh-CN", { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hour12: false });
}

export function mrMatchesTimeFilter(value: string, filter: string) {
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

export function hasNestedVerticalScrollRoom(target: HTMLElement | null, boundary: HTMLElement, deltaY: number) {
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

export function repoNameFromGitUrl(value: string) {
  const normalized = value.trim().replace(/\.git$/i, "");
  const path = normalized.includes(":") && !normalized.includes("://")
    ? normalized.split(":").pop() || normalized
    : normalized.replace(/^https?:\/\/[^/]+\//i, "").replace(/^ssh:\/\/[^/]+\//i, "");
  return path.split("/").filter(Boolean).pop() || normalized;
}

export function formatFindingLocation(finding: Pick<Finding, "file_path" | "line_start" | "line_end">) {
  if (!finding.line_start) return finding.file_path;
  if (finding.line_end && finding.line_end !== finding.line_start) {
    return `${finding.file_path}:${finding.line_start}-${finding.line_end}`;
  }
  return `${finding.file_path}:${finding.line_start}`;
}

export function formatFindingLineRange(finding: Pick<Finding, "line_start" | "line_end">) {
  if (!finding.line_start) return "行号 --";
  if (finding.line_end && finding.line_end !== finding.line_start) {
    return `L${finding.line_start}-L${finding.line_end}`;
  }
  return `L${finding.line_start}`;
}

export function shortPath(value: string) {
  if (!value || value === "--") return "--";
  const parts = value.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.length > 3 ? parts.slice(-3).join("/") : value;
}

export function providerLabel(provider: string) {
  if (provider === "github") return "GitHub";
  if (provider === "codehub") return "CodeHub";
  return provider || "--";
}

export function isRootUser(user: User | null) {
  return user?.global_role === "root";
}

export function canCreateProject(user: User | null) {
  return isRootUser(user) || user?.global_role === "project_admin";
}

export function isProjectAdminRole(role: string, user: User | null) {
  return isRootUser(user) || ["project_admin", "system_admin"].includes(role);
}

export function canAccessProjectAdminView(view: ViewKey) {
  return ["agents", "rules", "tools", "queue", "users", "settings", "policy", "repos"].includes(view);
}

export function textCodeLines(value: string, startLine = 1): ParsedDiffLine[] {
  const lines = String(value || "").split(/\r?\n/);
  return lines.map((content, index) => ({
    kind: "context",
    oldLine: startLine + index,
    newLine: startLine + index,
    content
  }));
}

export function sourceCodeWindow(source: string, startLine: number, endLine: number): ParsedDiffLine[] {
  const allLines = source.split(/\r?\n/);
  const safeStart = Math.max(1, startLine - SOURCE_CONTEXT_RADIUS);
  const safeEnd = Math.min(allLines.length, Math.max(endLine, startLine) + SOURCE_CONTEXT_RADIUS);
  return allLines.slice(safeStart - 1, safeEnd).map((content, index) => ({
    kind: "context",
    oldLine: safeStart + index,
    newLine: safeStart + index,
    content
  }));
}

export function diffCodeWindow(patch: string, startLine: number, endLine: number): ParsedDiffLine[] {
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
  let safeStart = Math.max(0, matchIndex - SOURCE_CONTEXT_RADIUS);
  while (safeStart > 0 && parsed[safeStart].kind !== "meta" && matchIndex - safeStart < SOURCE_CONTEXT_RADIUS * 2 + 2) {
    safeStart -= 1;
  }
  const safeEnd = Math.min(parsed.length, matchIndex + SOURCE_CONTEXT_RADIUS + 1);
  return parsed.slice(safeStart, safeEnd);
}

export function parseUnifiedPatch(patch: string): ParsedDiffLine[] {
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

export function buildFileTree(files: MrChangedFile[]) {
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

export function basename(path: string) {
  const parts = String(path || "").split("/").filter(Boolean);
  return parts[parts.length - 1] || path || "--";
}

export function normalizeRepositoryPath(value: string) {
  let normalized = String(value || "")
    .replace(/\\/g, "/")
    .replace(/[?#].*$/, "")
    .replace(/^file:\/+/, "")
    .trim();
  normalized = normalized.replace(/^\.\//, "").replace(/^\/+/, "");
  const anchors = ["/src/main/", "/src/test/", "/src/", "/pom.xml", "/build.gradle", "/settings.gradle", "/package.json"];
  for (const anchor of anchors) {
    const index = normalized.lastIndexOf(anchor);
    if (index >= 0) return normalized.slice(index + 1);
  }
  return normalized;
}

export function matchRepositoryPath(value: string, candidates: string[]) {
  const normalized = normalizeRepositoryPath(value);
  if (!normalized) return "";
  const normalizedCandidates = candidates.map((candidate) => ({
    raw: candidate,
    normalized: normalizeRepositoryPath(candidate)
  }));
  const exact = normalizedCandidates.find((candidate) => candidate.normalized === normalized);
  if (exact) return exact.raw;
  const suffix = normalizedCandidates.find((candidate) => (
    candidate.normalized.endsWith(`/${normalized}`) || normalized.endsWith(`/${candidate.normalized}`)
  ));
  return suffix?.raw || normalized;
}

export function readPathMap(map: Record<string, string>, filePath: string) {
  const key = matchRepositoryPath(filePath, Object.keys(map));
  return key ? map[key] || "" : "";
}
