import React, { useEffect, useState } from "react";
import {
  Check,
  Circle,
  ClipboardList,
  FileCode2,
  Folder,
  Loader2,
  ShieldCheck,
  Trash2,
  X
} from "lucide-react";
import { isStandardSkillAssetPath, normalizeSkillBundleAssetPath, skillRootNameFromFiles } from "../skillUploadPaths";
import { viewTitle } from "./Layout";
import { agentLabel, parseJsonArray, safeJson } from "./ReviewViews";
import {
  ViewKey,
  User,
  Repo,
  StaticToolAvailabilityItem,
  StaticToolAvailability,
  LlmSettingsForm,
  VcsTokenForm,
  ProjectVcsSettingsForm,
  StorageSettingsForm,
  ReviewSettingsForm,
  BudgetEffortForm,
  BudgetSettingsForm,
  AgentSettingsForm,
  ToolSettingsForm,
  STATIC_TOOL_SWITCHES,
  DEFAULT_STATIC_TOOL_ENABLED,
  QueueSettingsForm,
  PublishSettingsForm,
  DataSettingsForm,
  AgentBindingDetail,
  AgentBindingEditorOptions,
  LlmTestState,
  FormActionState,
  SuccessNotice,
  api,
  listItems,
  readUploadText,
  readableFileSize,
  uploadSkillBundleToProject,
  validateSkillBundle,
  splitCsv,
  clampLlmTimeout,
  clampLlmOutputTokens,
  positiveNumber,
  csvValue,
  recordValue,
  compactMetadata,
  skillAssetKind,
  skillAssetSummary,
  skillAssetManifest,
  skillAssetPathPreview,
  skillBundleContent,
  boolValue,
  staticToolPolicyValue,
  staticRunnerPayload,
  statusLabel,
  providerLabel
} from "../shared";

const RULE_DOCUMENT_TEMPLATE_NAME = "安全检视规范模板.md";
const RULE_DOCUMENT_TEMPLATE = `# 安全检视规范模板

## SEC-AUTH-001 管理接口鉴权检查

### 规范说明
管理端、运营端、批量处理、资金或敏感数据接口必须做身份认证和权限校验。新增或修改接口时，如果能修改业务状态、导出敏感数据、执行审批或触发补偿任务，必须明确校验当前用户权限。

### 证据要求
- 新增或修改 Controller、Handler、RPC 接口、定时任务触发入口或管理 API
- 接口涉及审批、退款、配置、导出、用户权限、资金或敏感数据
- 源码中缺少权限注解、权限服务调用、角色校验或统一鉴权链路证据

### 误报模式
- 普通只读健康检查、公开元数据查询或静态资源接口
- 权限由统一网关或切面处理，且代码中能看到明确注解、拦截器或路由配置
- 测试代码、demo 代码或本地调试入口

### 修复建议
在入口处增加认证和授权校验；使用统一权限组件校验角色、资源范围和操作类型；补充未授权访问测试和审计记录。`;

const SKILL_TEMPLATE_NAME = "安全检视 Skill 模板";
const SKILL_TEMPLATE_KEY = "security-review-skill-template";
const SKILL_MD_TEMPLATE = `---
name: security-review-skill-template
description: Review backend merge requests for authentication, sensitive data, and Redis cache safety risks.
---

# Security Review Skill Template

Use this Skill for backend Java or TypeScript service changes involving APIs, authorization, sensitive data, or cache writes.

The reviewer must inspect every checkpoint from \`references/security-review-rules.md\` independently. When a checkpoint is hit, the finding must use the checkpoint id exactly as defined in the reference document. Do not replace a Skill checkpoint id with a nearby platform rule, bound standard, expert persona rule, or free-form category.

Priority order for conflicting guidance:

1. Skill checkpoint
2. Bound project standard
3. Expert persona

If the source does not satisfy a checkpoint's required evidence, return no finding for that checkpoint. If the source matches a false positive pattern, return no finding for that checkpoint.`;

const SKILL_REFERENCE_TEMPLATE_PATH = "references/security-review-rules.md";
const SKILL_REFERENCE_TEMPLATE = `# Security Review Rules

## SEC-AUTH-001 管理接口鉴权检查
- severity: high
- applies_to: src/main/java/**,src/**/*.ts

### 检查点
管理端、运营端、批量处理、资金或敏感数据接口必须做身份认证和权限校验。新增或修改接口时，如果能修改业务状态、导出敏感数据、执行审批或触发补偿任务，必须明确校验当前用户权限。

### 证据要求
- 新增或修改 Controller、Handler、RPC 接口、定时任务触发入口或管理 API
- 接口涉及审批、退款、配置、导出、用户权限、资金或敏感数据
- 源码中缺少权限注解、权限服务调用、角色校验或统一鉴权链路证据

### 误报模式
- 普通只读健康检查、公开元数据查询或静态资源接口
- 权限由统一网关或切面处理，且代码中能看到明确注解、拦截器或路由配置
- 测试代码、demo 代码或本地调试入口

### 修复建议
在入口处增加认证和授权校验；使用统一权限组件校验角色、资源范围和操作类型；补充未授权访问测试和审计记录。

## SEC-DATA-002 敏感数据输出检查
- severity: high
- applies_to: src/main/java/**,src/**/*.ts

### 检查点
接口响应、日志、异常消息、导出文件和异步消息不能直接输出手机号、身份证号、银行卡、token、密钥、密码、个人地址等敏感字段。必须脱敏、过滤或只返回必要字段。

### 证据要求
- 代码读取或返回 user、customer、account、token、secret、password、mobile、idCard、bankCard 等敏感字段
- 字段进入响应 DTO、日志、异常、导出内容或消息体
- 缺少脱敏函数、字段白名单、权限过滤或安全审计说明

### 误报模式
- 字段已经经过 mask、desensitize、redact、encrypt 或等价处理
- 仅内部测试 fixture 或模拟数据
- 日志只记录不可逆 hash、traceId 或非敏感业务 id

### 修复建议
使用响应白名单和脱敏工具；日志中只保留必要的 traceId、业务 id 或不可逆摘要；为敏感字段输出增加单元测试。

## REDIS-TTL-002 Redis 业务缓存 TTL 检查
- severity: medium
- applies_to: src/main/java/**,src/**/*.ts

### 检查点
业务缓存写入 Redis 时必须设置过期时间。永久配置 key、feature flag、灰度开关、系统配置 key 不属于本检查点。

### 证据要求
- 使用 redisTemplate.opsForValue().set、set、hset 或等价 Redis 写入
- key 属于用户状态、订单详情、审批状态、任务进度或业务结果缓存
- 缺少 Duration、expire、setEx、EX 参数或等价过期时间

### 误报模式
- 永久配置 key，例如 system:feature:config
- feature flag、灰度开关、系统配置等明确永久 key
- 代码紧随其后调用 expire 设置过期时间

### 修复建议
为业务缓存设置合理 TTL；永久 key 必须用常量命名并注释说明 permanent/config 语义；补充缓存过期行为测试。`;

function formatValidationFailures(report: Record<string, unknown>) {
  const failures = Array.isArray(report.failures) ? report.failures : [];
  if (!failures.length) return "Skill 校验未通过";
  return failures
    .map((item) => {
      if (!item || typeof item !== "object") return String(item);
      const row = item as Record<string, unknown>;
      return [row.path, row.checkpoint_id, row.message].filter(Boolean).join(" · ");
    })
    .join("\n");
}

function skillReferenceTemplateAssets(content: string) {
  return content.includes(SKILL_REFERENCE_TEMPLATE_PATH)
    ? [{ asset_path: SKILL_REFERENCE_TEMPLATE_PATH, content: SKILL_REFERENCE_TEMPLATE }]
    : [];
}

export function ConfigWorkspace({
  view,
  projectId,
  repos,
  reload,
  setMessage,
  canEdit,
  canManageSystem
}: {
  view: ViewKey;
  projectId: string;
  repos: Repo[];
  reload: () => Promise<void>;
  setMessage: (value: string) => void;
  canEdit: boolean;
  canManageSystem: boolean;
}) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
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
    default_api_key: "",
    default_api_key_has_value: false,
    default_api_key_masked: "",
    request_timeout_seconds: "120",
    max_output_tokens: "8192",
    enable_stream: true
  });
  const [projectVcsForm, setProjectVcsForm] = useState<ProjectVcsSettingsForm>({
    codehub_token: "",
    codehub_token_env: "",
    codehub_endpoint: "",
    github_token: "",
    github_token_env: "",
    github_endpoint: ""
  });
  const [projectVcsStoredTokens, setProjectVcsStoredTokens] = useState({ codehub_token: "", github_token: "" });
  const [reviewForm, setReviewForm] = useState<ReviewSettingsForm>({
    effort: "standard",
    max_findings_per_mr: "40",
    max_added_lines_per_mr: "2000",
    min_confidence: "0.75",
    enable_full_repo_context: true
  });
  const [budgetForm, setBudgetForm] = useState<BudgetSettingsForm>({
    standard: { max_llm_calls: "80", max_wall_seconds: "1800", max_output_tokens: "16000", max_findings: "80" },
    deep: { max_llm_calls: "120", max_wall_seconds: "2400", max_output_tokens: "24000", max_findings: "120" }
  });
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
  const [queueForm, setQueueForm] = useState<QueueSettingsForm>({ poll_interval_seconds: "300", max_concurrency: "1", max_attempts: "3", heartbeat_timeout_seconds: "600" });
  const [publishForm, setPublishForm] = useState<PublishSettingsForm>({ require_manual_confirmation: true, dry_run: false, allowed_severities: "critical, high, medium, low" });
  const [dataForm, setDataForm] = useState<DataSettingsForm>({ prompt_retention: "hash_only", diff_max_lines_to_llm: "4000", sensitive_paths: "infra/secrets/**, config/prod/**, **/*.pem, **/*.p12", fallback_on_violation: "skip_file" });
  const [llmTest, setLlmTest] = useState<LlmTestState>({ status: "idle", message: "" });
  const [toolSave, setToolSave] = useState<FormActionState>({ status: "idle", message: "" });
  const [successNotice, setSuccessNotice] = useState<SuccessNotice | null>(null);
  const [agentQuality, setAgentQuality] = useState<Record<string, unknown>[]>([]);
  const [reviewQualityMetrics, setReviewQualityMetrics] = useState<Record<string, unknown>>({});
  const [ruleDocs, setRuleDocs] = useState<Record<string, unknown>[]>([]);
  const [ruleBindings, setRuleBindings] = useState<Record<string, unknown>[]>([]);
  const [customSkills, setCustomSkills] = useState<Record<string, unknown>[]>([]);
  const [skillAssets, setSkillAssets] = useState<Record<string, unknown>[]>([]);
  const [skillBindings, setSkillBindings] = useState<Record<string, unknown>[]>([]);
  const [toolBindings, setToolBindings] = useState<Record<string, unknown>[]>([]);
  const [userPermissionTab, setUserPermissionTab] = useState<"requests" | "members">("requests");
  const [joinRequests, setJoinRequests] = useState<Record<string, unknown>[]>([]);
  const [reviewingJoinRequestId, setReviewingJoinRequestId] = useState("");
  const [reviewingJoinRequestAction, setReviewingJoinRequestAction] = useState<"approved" | "rejected" | "">("");
  const [removingMemberId, setRemovingMemberId] = useState("");
  const [changingMemberRoleId, setChangingMemberRoleId] = useState("");
  const [memberRoleDrafts, setMemberRoleDrafts] = useState<Record<string, string>>({});
  const [invitations, setInvitations] = useState<Record<string, unknown>[]>([]);
  const [inviteRole, setInviteRole] = useState("developer");
  const [agentTab, setAgentTab] = useState<"create" | "list">("create");
  const [ruleContent, setRuleContent] = useState(RULE_DOCUMENT_TEMPLATE);
  const [ruleDocName, setRuleDocName] = useState(RULE_DOCUMENT_TEMPLATE_NAME);
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
  const [ruleDocUploadInfo, setRuleDocUploadInfo] = useState("");
  const [skillName, setSkillName] = useState("团队自定义检视 Skill");
  const [skillKey, setSkillKey] = useState("team-custom-review");
  const [skillAgentKey, setSkillAgentKey] = useState("team_custom_agent");
  const [skillBundleFiles, setSkillBundleFiles] = useState<File[]>([]);
  const [skillBundleInfo, setSkillBundleInfo] = useState("");
  const [skillValidationReport, setSkillValidationReport] = useState<Record<string, unknown> | null>(null);
  const [skillAssetPath, setSkillAssetPath] = useState("references/team-rules.md");
  const [skillAssetSkillKey, setSkillAssetSkillKey] = useState("team-custom-review");
  const [skillAssetContent, setSkillAssetContent] = useState("## TEAM-RULE-001 团队自定义规范\n\n### 规范说明\n在这里填写团队规则说明。\n\n### 检查点\n- 检查点 1。\n- 检查点 2。\n\n### 如何检查\n1. 读取当前 MR diff。\n2. 对照规则逐条检查。\n\n### 反例\n```java\n// bad example\n```\n\n### 正例\n```java\n// good example\n```\n");
  const [skillContent, setSkillContent] = useState(SKILL_MD_TEMPLATE);
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
        const [profiles, rules, bindings, expertRuleBindings, skills, assets, expertSkillBindings, qualityData, qualityMetrics] = await Promise.all([
          api<Record<string, unknown>[] | { items: Record<string, unknown>[] }>(`/api/projects/${projectId}/expert-profiles`),
          api<Record<string, unknown>[] | { items: Record<string, unknown>[] }>(`/api/projects/${projectId}/rule-documents`),
          api<Record<string, unknown>[] | { items: Record<string, unknown>[] }>(`/api/projects/${projectId}/expert-tool-bindings`),
          api<Record<string, unknown>[] | { items: Record<string, unknown>[] }>(`/api/projects/${projectId}/expert-rule-bindings`),
          api<Record<string, unknown>[] | { items: Record<string, unknown>[] }>(`/api/projects/${projectId}/custom-skills`),
          api<Record<string, unknown>[] | { items: Record<string, unknown>[] }>(`/api/projects/${projectId}/custom-skill-assets`),
          api<Record<string, unknown>[] | { items: Record<string, unknown>[] }>(`/api/projects/${projectId}/expert-skill-bindings`),
          api<Record<string, unknown>[] | { items: Record<string, unknown>[] }>(`/api/projects/${projectId}/agents/quality`),
          api<Record<string, unknown>>(`/api/projects/${projectId}/review-quality/metrics`)
        ]);
        setRows(listItems(profiles));
        setRuleDocs(listItems(rules));
        setToolBindings(listItems(bindings));
        setRuleBindings(listItems(expertRuleBindings));
        setCustomSkills(listItems(skills));
        setSkillAssets(listItems(assets));
        setSkillBindings(listItems(expertSkillBindings));
        setAgentQuality(listItems(qualityData));
        setReviewQualityMetrics(qualityMetrics || {});
      }
      else if (view === "users") {
        const [members, requests, invitationData] = await Promise.all([
          api<Record<string, unknown>[]>(`/api/projects/${projectId}/members`),
          api<{ items: Record<string, unknown>[] }>(`/api/projects/${projectId}/join-requests`),
          api<{ items: Record<string, unknown>[] }>(`/api/projects/${projectId}/invitations`)
        ]);
        setRows(members);
        setJoinRequests(requests.items || []);
        setInvitations(invitationData.items || []);
      }
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
      const vcsPolicy = { ...recordValue(settingsMap.vcs_policy) };
      const reviewPolicy = { ...recordValue(effectiveRoot.review_policy), ...recordValue(settingsMap.review_policy) };
      const budgetPolicy = { ...recordValue(effectiveRoot.budget_policy), ...recordValue(settingsMap.budget_policy) };
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
        default_api_key: "",
        default_api_key_has_value: Boolean(llm.default_api_key_has_value),
        default_api_key_masked: String(llm.default_api_key_masked ?? ""),
        request_timeout_seconds: String(llm.request_timeout_seconds ?? "120"),
        max_output_tokens: String(llm.max_output_tokens ?? "8192"),
        enable_stream: llm.enable_stream !== false
      });
      setProjectVcsForm({
        codehub_token: "",
        codehub_token_env: String(vcsPolicy.codehub_token_env ?? recordValue(effectiveRoot.codehub).default_token_env ?? ""),
        codehub_endpoint: String(vcsPolicy.codehub_endpoint ?? recordValue(effectiveRoot.codehub).default_endpoint ?? ""),
        github_token: "",
        github_token_env: String(vcsPolicy.github_token_env ?? recordValue(effectiveRoot.github).default_token_env ?? ""),
        github_endpoint: String(vcsPolicy.github_endpoint ?? recordValue(effectiveRoot.github).default_endpoint ?? "")
      });
      setProjectVcsStoredTokens({
        codehub_token: String(vcsPolicy.codehub_token ?? ""),
        github_token: String(vcsPolicy.github_token ?? "")
      });
      setReviewForm({
        effort: String(reviewPolicy.effort ?? "standard"),
        max_findings_per_mr: String(reviewPolicy.max_findings_per_mr ?? reviewPolicy.max_findings ?? "40"),
        max_added_lines_per_mr: String(reviewPolicy.max_added_lines_per_mr ?? "2000"),
        min_confidence: String(reviewPolicy.min_confidence ?? "0.75"),
        enable_full_repo_context: boolValue(reviewPolicy.enable_full_repo_context, true)
      });
      const budgetEfforts = recordValue(budgetPolicy.efforts);
      const standardBudget = recordValue(budgetEfforts.standard);
      const deepBudget = recordValue(budgetEfforts.deep);
      setBudgetForm({
        standard: {
          max_llm_calls: String(standardBudget.max_llm_calls ?? "80"),
          max_wall_seconds: String(standardBudget.max_wall_seconds ?? "1800"),
          max_output_tokens: String(standardBudget.max_output_tokens ?? "16000"),
          max_findings: String(standardBudget.max_findings ?? "80")
        },
        deep: {
          max_llm_calls: String(deepBudget.max_llm_calls ?? "120"),
          max_wall_seconds: String(deepBudget.max_wall_seconds ?? "2400"),
          max_output_tokens: String(deepBudget.max_output_tokens ?? "24000"),
          max_findings: String(deepBudget.max_findings ?? "120")
        }
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
        max_concurrency: String(queuePolicy.max_concurrency ?? "1"),
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

  function applyRuleTemplate() {
    setRuleDocName(RULE_DOCUMENT_TEMPLATE_NAME);
    setRuleContent(RULE_DOCUMENT_TEMPLATE);
    setRuleDocUploadInfo("已填入规范模板，可按团队规则修改");
    setMessage("已填入规范模板");
  }

  function applySkillTemplate() {
    setSkillName(SKILL_TEMPLATE_NAME);
    setSkillKey(SKILL_TEMPLATE_KEY);
    setSkillContent(SKILL_MD_TEMPLATE);
    setSkillBundleFiles([]);
    setSkillBundleInfo("已填入 SKILL.md 和 references/security-review-rules.md 模板");
    setSkillAssetPath(SKILL_REFERENCE_TEMPLATE_PATH);
    setSkillAssetContent(SKILL_REFERENCE_TEMPLATE);
    setSkillAssetSkillKey(SKILL_TEMPLATE_KEY);
    setSkillValidationReport(null);
    setMessage("已填入 Skill 模板：SKILL.md 和 references/security-review-rules.md");
  }

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

  async function handleRuleMarkdownFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".md")) {
      setMessage("请选择 .md 格式的规范文档");
      return;
    }
    const content = await readUploadText(file);
    setRuleDocName(file.name);
    setRuleContent(content);
    setRuleDocUploadInfo(`${file.name} · ${readableFileSize(file.size)}`);
    setMessage("Markdown 规范已读取，可直接上传并绑定");
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
    if (skillBundleFiles.length) {
      const result = await uploadSkillBundleToProject({
        projectId,
        agentKey: skillAgentKey,
        skillName,
        skillKey,
        files: skillBundleFiles
      });
      setSkillKey(result.skillKey);
      setSkillValidationReport(result.validation || null);
      setSkillBundleFiles([]);
      setSkillBundleInfo("");
      setMessage(`Skill 文件夹已上传并绑定，资源 ${result.assetCount} 个`);
      await loadConfigView();
      return;
    }
    if (!skillName.trim() || !skillContent.trim()) return;
    const templateAssets = skillReferenceTemplateAssets(skillContent);
    const validation = await validateSkillBundle({ projectId, skillName, skillKey, content: skillContent, assets: templateAssets });
    setSkillValidationReport(validation);
    if (!validation.ok) {
      setMessage(formatValidationFailures(validation));
      return;
    }
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
    for (const asset of templateAssets) {
      await api(`/api/projects/${projectId}/custom-skill-assets`, {
        method: "POST",
        body: JSON.stringify({
          skill_key: createdSkillKey,
          asset_path: asset.asset_path,
          asset_type: "reference",
          content: asset.content,
          executable: false
        })
      });
    }
    if (skillAgentKey) {
      await api(`/api/projects/${projectId}/expert-skill-bindings`, {
        method: "POST",
        body: JSON.stringify({ agent_key: skillAgentKey, skill_key: createdSkillKey, priority: 100, enabled: true })
      });
    }
    setMessage("自定义 Skill 已创建并绑定");
    await loadConfigView();
  }

  function handleSkillBundleFiles(event: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!files.length) return;
    const rootName = skillRootNameFromFiles(files);
    if (rootName && (!skillName.trim() || skillName === "团队自定义检视 Skill")) setSkillName(rootName);
    if (rootName && (!skillKey.trim() || skillKey === "team-custom-review")) setSkillKey(rootName);
    const totalSize = files.reduce((sum, file) => sum + file.size, 0);
    const assetPaths = files
      .map(normalizeSkillBundleAssetPath)
      .filter((path) => path && !path.includes("..") && isStandardSkillAssetPath(path));
    const hasSkillMd = assetPaths.some((path) => path === "SKILL.md");
    setSkillBundleFiles(files);
    setSkillValidationReport(null);
    setSkillBundleInfo(`${rootName || "已选择文件"} · 有效资源 ${assetPaths.length}/${files.length} 个 · ${readableFileSize(totalSize)}${hasSkillMd ? "" : " · 缺少 SKILL.md"}`);
    setMessage(hasSkillMd ? "Skill 文件夹已选择，可上传并绑定" : "Skill 文件夹缺少 SKILL.md，请重新选择");
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

  async function removeMember(row: Record<string, unknown>) {
    const memberId = String(row.id || "");
    if (!memberId) return;
    const displayName = String(row.display_name || row.username || row.user_id || "该用户");
    const confirmed = window.confirm(`确认移除 ${displayName} 在当前项目中的权限吗？`);
    if (!confirmed) return;
    setRemovingMemberId(memberId);
    try {
      await api(`/api/projects/${projectId}/members/${memberId}`, { method: "DELETE" });
      setMessage(`已移除 ${displayName} 的项目权限`);
      setSuccessNotice({
        title: "项目权限已移除",
        message: `${displayName} 已不再拥有当前项目访问权限。`,
        detail: "成员列表已刷新。"
      });
      await loadConfigView();
      await reload();
    } finally {
      setRemovingMemberId("");
    }
  }

  async function updateMemberRole(row: Record<string, unknown>, role: string) {
    const memberId = String(row.id || "");
    if (!memberId) return;
    const displayName = String(row.display_name || row.username || row.user_id || "该用户");
    setChangingMemberRoleId(memberId);
    try {
      await api(`/api/projects/${projectId}/members/${memberId}`, {
        method: "PATCH",
        body: JSON.stringify({ role })
      });
      setMessage(`${displayName} 已设为 ${role}`);
      setSuccessNotice({
        title: "项目角色已更新",
        message: `${displayName} 的项目角色已调整为 ${role}。`,
        detail: "成员列表已刷新，新的项目权限立即生效。"
      });
      await loadConfigView();
      await reload();
    } finally {
      setChangingMemberRoleId("");
    }
  }

  async function reviewJoinRequest(row: Record<string, unknown>, status: "approved" | "rejected") {
    const requestId = String(row.id || "");
    if (!requestId) return;
    const applicant = String(row.display_name || row.username || row.user_id || "该用户");
    setReviewingJoinRequestId(requestId);
    setReviewingJoinRequestAction(status);
    try {
      const result = await api<Record<string, unknown>>(`/api/projects/${projectId}/join-requests/${requestId}`, {
        method: "PATCH",
        body: JSON.stringify({ status })
      });
      const approved = status === "approved";
      const message = approved ? `${applicant} 已加入项目` : `已拒绝 ${applicant} 的加入申请`;
      setMessage(message);
      setSuccessNotice({
        title: approved ? "加入申请已批准" : "加入申请已拒绝",
        message,
        detail: approved
          ? `授权角色：${String(result.requested_role || row.requested_role || "developer")}。成员列表和申请状态已刷新。`
          : "申请状态已更新为 rejected，用户可在项目选择页看到最新状态。"
      });
      await loadConfigView();
      await reload();
    } finally {
      setReviewingJoinRequestId("");
      setReviewingJoinRequestAction("");
    }
  }

  async function createInvitation() {
    const result = await api<{ invite_code: string }>(`/api/projects/${projectId}/invitations`, {
      method: "POST",
      body: JSON.stringify({ role: inviteRole })
    });
    setSuccessNotice({
      title: "邀请码已创建",
      message: result.invite_code,
      detail: "邀请码不限制使用次数，只展示一次，请发送给需要加入项目的用户。"
    });
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
    const value: Record<string, unknown> = {
      default_provider: llmForm.default_provider.trim(),
      default_base_url: llmForm.default_base_url.trim(),
      default_model: llmForm.default_model.trim(),
      request_timeout_seconds: clampLlmTimeout(llmForm.request_timeout_seconds),
      max_output_tokens: clampLlmOutputTokens(llmForm.max_output_tokens),
      enable_stream: llmForm.enable_stream
    };
    if (llmForm.default_api_key.trim()) value.default_api_key = llmForm.default_api_key.trim();
    await saveStructuredSetting("llm_policy", "模型服务配置", value);
  }

  async function saveProjectVcsSettings() {
    await saveStructuredSetting("vcs_policy", "代码平台访问配置", {
      codehub_token: projectVcsForm.codehub_token.trim() || projectVcsStoredTokens.codehub_token || null,
      codehub_token_env: projectVcsForm.codehub_token_env.trim() || null,
      codehub_endpoint: projectVcsForm.codehub_endpoint.trim() || null,
      github_token: projectVcsForm.github_token.trim() || projectVcsStoredTokens.github_token || null,
      github_token_env: projectVcsForm.github_token_env.trim() || null,
      github_endpoint: projectVcsForm.github_endpoint.trim() || null
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
          default_api_key: llmForm.default_api_key.trim(),
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
      max_added_lines_per_mr: positiveNumber(reviewForm.max_added_lines_per_mr, 2000, 1000000),
      min_confidence: Number(reviewForm.min_confidence),
      enable_full_repo_context: reviewForm.enable_full_repo_context
    });
  }

  function updateBudgetEffort(effort: keyof BudgetSettingsForm, field: keyof BudgetEffortForm, value: string) {
    setBudgetForm({
      ...budgetForm,
      [effort]: {
        ...budgetForm[effort],
        [field]: value
      }
    });
  }

  function budgetPayload(row: BudgetEffortForm) {
    return {
      max_llm_calls: positiveNumber(row.max_llm_calls, 80, 500),
      max_wall_seconds: positiveNumber(row.max_wall_seconds, 1800, 7200),
      max_output_tokens: positiveNumber(row.max_output_tokens, 16000, 64000),
      max_findings: positiveNumber(row.max_findings, 80, 300),
      on_exceed: "degrade"
    };
  }

  async function saveBudgetSettings() {
    await saveStructuredSetting("budget_policy", "检视预算与熔断", {
      efforts: {
        standard: budgetPayload(budgetForm.standard),
        deep: budgetPayload(budgetForm.deep)
      }
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
    return agentRuleDetails(agentKey).length;
  }

  function agentToolCount(agentKey: string) {
    return toolBindings.filter((binding) => String(binding.agent_key) === agentKey && Boolean(binding.enabled)).length;
  }

  function agentToolNames(agentKey: string) {
    return toolBindings
      .filter((binding) => String(binding.agent_key) === agentKey && Boolean(binding.enabled))
      .map((binding) => `${String(binding.tool_name)} / ${String(binding.permission_level ?? "read_only")}`);
  }

  function agentSkillNames(agentKey: string) {
    return agentSkillDetails(agentKey).map((skill) => skill.title);
  }

  function agentRuleDetails(agentKey: string): AgentBindingDetail[] {
    const bindingsByDocId = new Map(
      ruleBindings
        .filter((binding) => String(binding.agent_key) === agentKey)
        .map((binding) => [String(binding.rule_document_id), binding])
    );
    return ruleDocs
      .filter((rule) => bindingsByDocId.has(String(rule.id)) || String(rule.name || "").includes(agentLabel(agentKey)) || String(rule.id || "").includes(agentKey))
      .map((rule) => {
        const binding = bindingsByDocId.get(String(rule.id));
        return {
          kind: "rule",
          title: String(rule.name || rule.id || "未命名规范"),
          subtitle: String(rule.doc_type || "规范文档"),
          content: String(rule.content || "暂无规范内容"),
          metadata: compactMetadata([
            ["文档 ID", rule.id],
            ["类型", rule.doc_type],
            ["版本", rule.version],
            ["状态", rule.status],
            ["优先级", binding?.priority],
            ["绑定 ID", binding?.id]
          ])
        };
      });
  }

  function agentSkillDetails(agentKey: string): AgentBindingDetail[] {
    const boundSkillKeys = new Set(
      skillBindings
        .filter((binding) => String(binding.agent_key) === agentKey && Boolean(binding.enabled))
        .map((binding) => String(binding.skill_key))
    );
    const bindingBySkillKey = new Map(
      skillBindings
        .filter((binding) => String(binding.agent_key) === agentKey && Boolean(binding.enabled))
        .map((binding) => [String(binding.skill_key), binding])
    );
    return customSkills
      .filter((skill) => boundSkillKeys.has(String(skill.skill_key)))
      .map((skill) => {
        const binding = bindingBySkillKey.get(String(skill.skill_key));
        const assets = skillAssets
          .filter((asset) => String(asset.skill_key) === String(skill.skill_key))
          .sort((left, right) => String(left.asset_path || "").localeCompare(String(right.asset_path || "")));
        const manifest = skillAssetManifest(assets);
        const bundleContent = skillBundleContent(skill, assets);
        return {
          kind: "skill",
          title: String(skill.name || skill.skill_key || "未命名 Skill"),
          subtitle: `${String(skill.skill_key || "custom skill")} · ${skillAssetSummary(assets)}`,
          bindingId: String(binding?.id || ""),
          skillKey: String(skill.skill_key || ""),
          assets: assets.map((asset) => ({
            path: String(asset.asset_path || "未命名资源"),
            type: skillAssetKind(asset),
            executable: Boolean(asset.executable)
          })),
          content: [
            "Bundle 文件清单",
            manifest,
            "",
            "Bundle 文件内容",
            bundleContent
          ].join("\n"),
          metadata: compactMetadata([
            ["Skill Key", skill.skill_key],
            ["描述", skill.description],
            ["Bundle 文件", skillAssetSummary(assets)],
            ["版本", skill.version],
            ["状态", skill.status],
            ["优先级", binding?.priority],
            ["绑定状态", binding?.enabled === false ? "停用" : "启用"],
            ["绑定 ID", binding?.id]
          ])
        };
      });
  }

  function agentSkillAssetDetails(agentKey: string): AgentBindingDetail[] {
    const boundSkillKeys = new Set(
      skillBindings
        .filter((binding) => String(binding.agent_key) === agentKey && Boolean(binding.enabled))
        .map((binding) => String(binding.skill_key))
    );
    return skillAssets
      .filter((asset) => boundSkillKeys.has(String(asset.skill_key)))
      .map((asset) => ({
        kind: "asset",
        title: String(asset.asset_path || "未命名资源"),
        subtitle: String(asset.skill_key || "Skill 资源"),
        content: String(asset.content || "暂无资源内容"),
        metadata: compactMetadata([
          ["Skill Key", asset.skill_key],
          ["资源路径", asset.asset_path],
          ["资源类型", asset.asset_type],
          ["可执行", asset.executable ? "是" : "否"],
          ["资源 ID", asset.id]
        ])
      }));
  }

  function agentQualityRow(agentKey: string) {
    return agentQuality.find((item) => String(item.agent_id) === agentKey) ?? {};
  }

  function projectBoundRuleCoverage() {
    const coverage = reviewQualityMetrics.bound_rule_coverage;
    return typeof coverage === "object" && coverage ? coverage as Record<string, unknown> : {};
  }

  function metricPercent(value: unknown) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? `${Math.round(parsed * 100)}%` : "--";
  }

  function skillValidationPreview() {
    if (!skillValidationReport) return null;
    const failures = Array.isArray(skillValidationReport.failures) ? skillValidationReport.failures as Record<string, unknown>[] : [];
    const warnings = Array.isArray(skillValidationReport.warnings) ? skillValidationReport.warnings as Record<string, unknown>[] : [];
    const checkpoints = Array.isArray(skillValidationReport.checkpoints) ? skillValidationReport.checkpoints as Record<string, unknown>[] : [];
    return (
      <div className={`skill-validation-preview ${skillValidationReport.ok ? "ok" : "error"}`}>
        <strong>{skillValidationReport.ok ? "Skill 校验通过" : "Skill 校验未通过"}</strong>
        <span>{checkpoints.length} 个 checkpoint · {warnings.length} 个警告 · {failures.length} 个错误</span>
        {failures.slice(0, 4).map((item, index) => (
          <p key={`failure-${index}`}>{String(item.path || "Skill")}：{String(item.message || "校验失败")}</p>
        ))}
        {warnings.slice(0, 4).map((item, index) => (
          <p key={`warning-${index}`}>{String(item.path || "Skill")}：{String(item.message || "需要确认")}</p>
        ))}
        {checkpoints.slice(0, 6).map((item, index) => (
          <p key={`checkpoint-${index}`}>{String(item.checkpoint_id || "--")} · {String(item.source_path || "SKILL.md")} · {String(item.false_positive_patterns || "未解析到误报模式").slice(0, 96)}</p>
        ))}
      </div>
    );
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
            <div className="agent-tab-panel agent-create-workbench">
              <div className="rule-upload-panel agent-create-panel">
                <div>
                  <strong>创建自定义专家 Agent</strong>
                  <span>定义专家画像、职责边界和触发范围；创建后在同页上传规范或 Skill 文件夹。</span>
                </div>
                <div className="rule-upload-form agent-main-form">
                  <input value={customAgentKey} onChange={(event) => setCustomAgentKey(event.target.value)} placeholder="agent-key，例如 payment_agent" disabled={!canEdit} />
                  <input value={customAgentName} onChange={(event) => setCustomAgentName(event.target.value)} placeholder="Agent 名称" disabled={!canEdit} />
                  <button type="button" onClick={createCustomAgent} disabled={!canEdit}>创建 Agent</button>
                </div>
                <div className="agent-editor-grid compact">
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
              <div className="agent-upload-grid">
                <div className="rule-upload-panel compact-upload-card">
                  <div>
                    <strong>上传 Markdown 规范</strong>
                    <span>选择 `.md` 文档后自动读取内容，再绑定到指定专家。</span>
                  </div>
                  <div className="template-action-row">
                    <button type="button" onClick={applyRuleTemplate} disabled={!canEdit}>
                      <ClipboardList size={14} />
                      使用规范模板
                    </button>
                    <a href="/templates/rule-document-template.md" target="_blank" rel="noreferrer">查看模板文件</a>
                  </div>
                  <div className="rule-upload-form compact-upload-form">
                    <input value={ruleDocName} onChange={(event) => setRuleDocName(event.target.value)} disabled={!canEdit} />
                    <select value={ruleDocAgentKey} onChange={(event) => setRuleDocAgentKey(event.target.value)} disabled={!canEdit}>
                      {rows.map((row, index) => {
                        const agentKey = String(row.agent_key || row.agent_id || `agent_${index}`);
                        return <option key={agentKey} value={agentKey}>{String(row.display_name || row.agent_key || row.agent_id || agentKey)}</option>;
                      })}
                    </select>
                    <button type="button" onClick={uploadRuleDocument} disabled={!canEdit || !ruleContent.trim()}>上传并绑定</button>
                  </div>
                  <label className="file-upload-dropzone">
                    <FileCode2 size={20} />
                    <span>{ruleDocUploadInfo || "选择 .md 规范文档"}</span>
                    <input type="file" accept=".md,text/markdown,text/plain" onChange={handleRuleMarkdownFile} disabled={!canEdit} />
                  </label>
                  {skillValidationPreview()}
                  <details className="compact-preview">
                    <summary>查看或微调规范内容</summary>
                    <textarea value={ruleContent} onChange={(event) => setRuleContent(event.target.value)} disabled={!canEdit} />
                  </details>
                </div>
                <div className="rule-upload-panel compact-upload-card">
                  <div>
                    <strong>上传标准 Skill 文件夹</strong>
                    <span>文件夹需包含 `SKILL.md`，支持 `references/`、`scripts/`、`assets/`。</span>
                  </div>
                  <div className="template-action-row">
                    <button type="button" onClick={applySkillTemplate} disabled={!canEdit}>
                      <ClipboardList size={14} />
                      使用 Skill 模板
                    </button>
                    <a href="/templates/security-review-skill-template/SKILL.md" target="_blank" rel="noreferrer">SKILL.md</a>
                    <a href="/templates/security-review-skill-template/references/security-review-rules.md" target="_blank" rel="noreferrer">references 规范</a>
                  </div>
                  <div className="rule-upload-form compact-upload-form">
                    <input value={skillName} onChange={(event) => setSkillName(event.target.value)} placeholder="Skill 名称" disabled={!canEdit} />
                    <input value={skillKey} onChange={(event) => setSkillKey(event.target.value)} placeholder="skill-key" disabled={!canEdit} />
                    <select value={skillAgentKey} onChange={(event) => setSkillAgentKey(event.target.value)} disabled={!canEdit}>
                      {rows.map((row, index) => {
                        const agentKey = String(row.agent_key || row.agent_id || `agent_${index}`);
                        return <option key={agentKey} value={agentKey}>{String(row.display_name || row.agent_key || row.agent_id || agentKey)}</option>;
                      })}
                    </select>
                    <button type="button" onClick={createCustomSkill} disabled={!canEdit}>{skillBundleFiles.length ? "上传并绑定文件夹" : "创建并绑定"}</button>
                  </div>
                  <label className="file-upload-dropzone">
                    <Folder size={20} />
                    <span>{skillBundleInfo || "选择 Skill 文件夹"}</span>
                    <input
                      type="file"
                      multiple
                      ref={(node) => {
                        if (node) {
                          node.setAttribute("webkitdirectory", "");
                          node.setAttribute("directory", "");
                        }
                      }}
                      onChange={handleSkillBundleFiles}
                      disabled={!canEdit}
                    />
                  </label>
                  <details className="compact-preview">
                    <summary>手动创建 SKILL.md 内容</summary>
                    <textarea value={skillContent} onChange={(event) => setSkillContent(event.target.value)} disabled={!canEdit} />
                  </details>
                </div>
                <div className="rule-upload-panel compact-upload-card">
                  <div>
                    <strong>补充单个 Skill 资源</strong>
                    <span>用于追加或覆盖某个 Skill 的 reference/script/asset 文件。</span>
                  </div>
                  <div className="rule-upload-form compact-upload-form">
                    <input value={skillAssetSkillKey} onChange={(event) => setSkillAssetSkillKey(event.target.value)} placeholder="skill-key" disabled={!canEdit} />
                    <input value={skillAssetPath} onChange={(event) => setSkillAssetPath(event.target.value)} placeholder="references/rules.md 或 scripts/check.py" disabled={!canEdit} />
                    <button type="button" onClick={uploadSkillAsset} disabled={!canEdit}>保存资源</button>
                  </div>
                  <details className="compact-preview" open>
                    <summary>资源内容</summary>
                    <textarea value={skillAssetContent} onChange={(event) => setSkillAssetContent(event.target.value)} disabled={!canEdit} />
                  </details>
                </div>
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
                <span>项目规则闭环 <strong>{metricPercent(projectBoundRuleCoverage().resolution_rate)}</strong></span>
                <span>未闭环 <strong>{String(projectBoundRuleCoverage().unresolved_count ?? 0)}</strong></span>
              </div>
              <div className="agent-config-list">
                {rows.map((row) => (
                  <AgentProfileCard
                    key={String(row.id || row.agent_key || row.agent_id)}
                    row={row}
                    projectId={projectId}
                    ruleCount={agentRuleCount(String(row.agent_key || row.agent_id))}
                    toolCount={agentToolCount(String(row.agent_key || row.agent_id))}
                    toolNames={agentToolNames(String(row.agent_key || row.agent_id))}
                    skillNames={agentSkillNames(String(row.agent_key || row.agent_id))}
                    ruleDetails={agentRuleDetails(String(row.agent_key || row.agent_id))}
                    skillDetails={agentSkillDetails(String(row.agent_key || row.agent_id))}
                    skillAssetDetails={agentSkillAssetDetails(String(row.agent_key || row.agent_id))}
                    bindingOptions={{
                      ruleDocs,
                      ruleBindings,
                      customSkills,
                      skillAssets,
                      skillBindings,
                      toolBindings,
                      staticToolAvailability
                    }}
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
          <div className="user-permission-tabs" role="tablist" aria-label="用户权限管理页签">
            <button type="button" className={userPermissionTab === "requests" ? "active" : ""} onClick={() => setUserPermissionTab("requests")}>
              用户权限审批
            </button>
            <button type="button" className={userPermissionTab === "members" ? "active" : ""} onClick={() => setUserPermissionTab("members")}>
              已加入用户管理
            </button>
          </div>
          {userPermissionTab === "requests" && (
            <>
              <div className="join-request-section">
                <div className="setting-form-head">
                  <strong>项目邀请码</strong>
                  <span>创建不限次数的邀请码，用户可在项目选择页直接加入。</span>
                </div>
                <div className="invite-create-row">
                  <select value={inviteRole} onChange={(event) => setInviteRole(event.target.value)} disabled={!canEdit}>
                    <option value="developer">developer</option>
                    <option value="reviewer">reviewer</option>
                    <option value="observer">observer</option>
                    {canManageSystem && <option value="project_admin">project_admin</option>}
                  </select>
                  <button type="button" onClick={createInvitation} disabled={!canEdit}>创建邀请码</button>
                </div>
                <ConfigTable
                  rows={invitations.map((item) => ({
                    ...item,
                    usage_limit: Number(item.max_uses) === 0 ? "不限" : String(item.max_uses ?? "--")
                  }))}
                  columns={["role", "status", "used_count", "usage_limit", "created_by_username", "created_at"]}
                />
              </div>
              <div className="join-request-section">
                <div className="setting-form-head">
                  <strong>加入申请</strong>
                  <span>普通用户提交加入项目申请后，项目管理员在这里审批。</span>
                </div>
                {joinRequests.map((row) => (
                  <article key={String(row.id)}>
                    <div>
                      <strong>{String(row.display_name || row.username || row.user_id)}</strong>
                      <span>{String(row.reason || "未填写申请原因")}</span>
                      <em>{String(row.status || "pending")} · {String(row.requested_role || "developer")}</em>
                    </div>
                    <div>
                      <button
                        type="button"
                        onClick={() => reviewJoinRequest(row, "approved")}
                        disabled={!canEdit || Boolean(reviewingJoinRequestId) || String(row.status) !== "pending"}
                      >
                        {reviewingJoinRequestId === String(row.id) && reviewingJoinRequestAction === "approved" ? "批准中..." : "批准"}
                      </button>
                      <button
                        type="button"
                        onClick={() => reviewJoinRequest(row, "rejected")}
                        disabled={!canEdit || Boolean(reviewingJoinRequestId) || String(row.status) !== "pending"}
                      >
                        {reviewingJoinRequestId === String(row.id) && reviewingJoinRequestAction === "rejected" ? "拒绝中..." : "拒绝"}
                      </button>
                    </div>
                  </article>
                ))}
                {!joinRequests.length && <div className="config-table-empty">暂无加入申请</div>}
              </div>
            </>
          )}
          {userPermissionTab === "members" && (
            <div className="joined-user-management">
              <div className="config-editor inline">
                <input value={memberName} onChange={(event) => setMemberName(event.target.value)} placeholder="username" disabled={!canEdit} />
                <button type="button" onClick={addMember} disabled={!canEdit}>添加开发者</button>
              </div>
              <div className="joined-user-list">
                {rows.map((row) => {
                  const memberId = String(row.id || "");
                  const currentRole = String(row.role || "developer");
                  const draftRole = memberRoleDrafts[memberId] ?? currentRole;
                  const roleChanged = draftRole !== currentRole;
                  return (
                    <article key={memberId}>
                      <div>
                        <strong>{String(row.display_name || row.username || row.user_id)}</strong>
                        <span>{String(row.username || "--")} · {String(row.email || "未配置邮箱")}</span>
                        <em>{currentRole} · {String(row.status || "active")}</em>
                      </div>
                      <div className="member-row-actions">
                        {canManageSystem && (
                          <div className="member-role-actions">
                            <select
                              value={draftRole}
                              onChange={(event) => setMemberRoleDrafts((previous) => ({ ...previous, [memberId]: event.target.value }))}
                              disabled={!canEdit || changingMemberRoleId === memberId}
                              aria-label={`${String(row.username || row.display_name || "用户")} 项目角色`}
                            >
                              <option value="observer">observer</option>
                              <option value="developer">developer</option>
                              <option value="reviewer">reviewer</option>
                              <option value="project_admin">project_admin</option>
                            </select>
                            <button
                              type="button"
                              onClick={() => updateMemberRole(row, draftRole)}
                              disabled={!canEdit || !roleChanged || changingMemberRoleId === memberId}
                            >
                              <ShieldCheck size={15} />
                              {changingMemberRoleId === memberId ? "保存中..." : "保存角色"}
                            </button>
                          </div>
                        )}
                        <button className="danger" type="button" onClick={() => removeMember(row)} disabled={!canEdit || removingMemberId === memberId}>
                          <Trash2 size={15} />
                          {removingMemberId === memberId ? "移除中..." : "移除权限"}
                        </button>
                      </div>
                    </article>
                  );
                })}
                {!rows.length && <div className="config-table-empty">暂无已加入用户</div>}
              </div>
            </div>
          )}
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
                <SettingField label="API Key">
                  <input type="password" value={llmForm.default_api_key} onChange={(event) => setLlmForm({ ...llmForm, default_api_key: event.target.value })} placeholder={llmForm.default_api_key_has_value ? "留空则保留已保存的 API Key" : "输入模型 API Key"} disabled={!canEdit} autoComplete="off" />
                </SettingField>
                <SettingField label="密钥来源">
                  <div className="setting-static-text">{llmForm.default_api_key_has_value ? `已保存 ${llmForm.default_api_key_masked || "API Key"}；重新输入后会覆盖。` : "API Key 会保存到 Common 服务的项目配置中，接口不会回显明文。"}</div>
                </SettingField>
              </div>
              <div className="setting-actions">
                <button type="button" onClick={testLlmSettings} disabled={!canEdit || llmTest.status === "testing"}>{llmTest.status === "testing" ? "测试中..." : "测试连接"}</button>
                <button type="button" onClick={saveLlmSettings} disabled={!canEdit}>保存模型配置</button>
              </div>
              {llmTest.message && <p className={`llm-test-result ${llmTest.status}`}>{llmTest.message}</p>}
            </article>

            <article className="setting-form-card">
              <div className="setting-form-head">
                <strong>代码平台访问配置</strong>
                <span>项目管理员按项目配置。同步 MR、读取 diff、获取 MR 文件信息统一使用这里的凭据，保证同项目所有用户看到同一批 MR 和同一套状态。</span>
              </div>
              <div className="setting-form-grid">
                <SettingField label="CodeHub Endpoint">
                  <input value={projectVcsForm.codehub_endpoint} onChange={(event) => setProjectVcsForm({ ...projectVcsForm, codehub_endpoint: event.target.value })} placeholder="https://codehub.example.com" disabled={!canEdit} />
                </SettingField>
                <SettingField label="CodeHub Token 环境变量">
                  <input value={projectVcsForm.codehub_token_env} onChange={(event) => setProjectVcsForm({ ...projectVcsForm, codehub_token_env: event.target.value })} placeholder="CODEHUB_TOKEN" disabled={!canEdit} />
                </SettingField>
                <SettingField label="CodeHub Token">
                  <input type="password" value={projectVcsForm.codehub_token} onChange={(event) => setProjectVcsForm({ ...projectVcsForm, codehub_token: event.target.value })} placeholder={projectVcsStoredTokens.codehub_token ? "已配置，留空不修改" : "用于拉取 MR 和读取 diff"} disabled={!canEdit} />
                </SettingField>
                <SettingField label="GitHub Endpoint">
                  <input value={projectVcsForm.github_endpoint} onChange={(event) => setProjectVcsForm({ ...projectVcsForm, github_endpoint: event.target.value })} placeholder="https://api.github.com" disabled={!canEdit} />
                </SettingField>
                <SettingField label="GitHub Token 环境变量">
                  <input value={projectVcsForm.github_token_env} onChange={(event) => setProjectVcsForm({ ...projectVcsForm, github_token_env: event.target.value })} placeholder="GITHUB_TOKEN" disabled={!canEdit} />
                </SettingField>
                <SettingField label="GitHub Token">
                  <input type="password" value={projectVcsForm.github_token} onChange={(event) => setProjectVcsForm({ ...projectVcsForm, github_token: event.target.value })} placeholder={projectVcsStoredTokens.github_token ? "已配置，留空不修改" : "用于拉取 PR 和读取 diff"} disabled={!canEdit} />
                </SettingField>
              </div>
              <div className="setting-actions">
                <button type="button" onClick={saveProjectVcsSettings} disabled={!canEdit}>保存代码平台配置</button>
              </div>
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
                <SettingField label="新增行数上限">
                  <input value={reviewForm.max_added_lines_per_mr} onChange={(event) => setReviewForm({ ...reviewForm, max_added_lines_per_mr: event.target.value })} disabled={!canEdit} />
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

            <article className="setting-form-card wide">
              <div className="setting-form-head">
                <strong>检视预算与熔断</strong>
                <span>控制整个 MR 检视过程的 LLM 调用次数、最长耗时、输出长度和问题数量，触发后会降级跳过剩余模型步骤。</span>
              </div>
              <div className="budget-policy-grid">
                {(["standard", "deep"] as Array<keyof BudgetSettingsForm>).map((effort) => (
                  <section className="budget-policy-card" key={effort}>
                    <div>
                      <strong>{effort === "standard" ? "Standard 日常检视" : "Deep 深度检视"}</strong>
                      <span>{effort === "standard" ? "推荐用于普通业务 MR" : "推荐用于安全敏感或大 MR"}</span>
                    </div>
                    <SettingField label="LLM 调用上限">
                      <input type="number" min="0" max="500" value={budgetForm[effort].max_llm_calls} onChange={(event) => updateBudgetEffort(effort, "max_llm_calls", event.target.value)} disabled={!canEdit} />
                    </SettingField>
                    <SettingField label="最长检视秒数">
                      <input type="number" min="0" max="7200" value={budgetForm[effort].max_wall_seconds} onChange={(event) => updateBudgetEffort(effort, "max_wall_seconds", event.target.value)} disabled={!canEdit} />
                    </SettingField>
                    <SettingField label="输出 Token 上限">
                      <input type="number" min="0" max="64000" value={budgetForm[effort].max_output_tokens} onChange={(event) => updateBudgetEffort(effort, "max_output_tokens", event.target.value)} disabled={!canEdit} />
                    </SettingField>
                    <SettingField label="最大问题数">
                      <input type="number" min="0" max="300" value={budgetForm[effort].max_findings} onChange={(event) => updateBudgetEffort(effort, "max_findings", event.target.value)} disabled={!canEdit} />
                    </SettingField>
                  </section>
                ))}
              </div>
              <div className="setting-actions">
                <button type="button" onClick={saveBudgetSettings} disabled={!canEdit}>保存预算策略</button>
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
                <SettingField label="项目内 MR 并发">
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

export function PersonalSettingsWorkspace({ user, setMessage }: { user: User | null; setMessage: (value: string) => void }) {
  const [vcsForm, setVcsForm] = useState<VcsTokenForm>({ codehub_token: "" });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState("");
  const [successNotice, setSuccessNotice] = useState<SuccessNotice | null>(null);

  async function loadPersonalSettings() {
    setLoading(true);
    try {
      const result = await api<{ items: Array<{ key: string; value: Record<string, unknown> }> }>("/api/me/settings");
      const map = new Map(result.items.map((item) => [item.key, item.value]));
      const tokens = map.get("vcs_tokens") || {};
      setVcsForm({
        codehub_token: "",
        codehub_token_has_value: Boolean(tokens.codehub_token_has_value),
        codehub_token_masked: String(tokens.codehub_token_masked || "")
      });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadPersonalSettings().catch((error) => setMessage(error instanceof Error ? error.message : String(error)));
  }, []);

  async function saveVcsTokens() {
    setSaving("tokens");
    try {
      await api("/api/me/settings/vcs_tokens", {
        method: "PATCH",
        body: JSON.stringify({
          value: {
            codehub_token: vcsForm.codehub_token.trim()
          }
        })
      });
      setMessage("个人 CodeHub Token 已保存");
      setSuccessNotice({ title: "CodeHub Token 已保存", message: "个人 CodeHub Token 只用于你手动提交已确认的检视意见，不参与 MR 同步、diff 读取和 AI 检视。" });
      await loadPersonalSettings();
    } finally {
      setSaving("");
    }
  }

  return (
    <section className="config-workspace">
      <ConfigHeader title="个人设置" subtitle="个人配置只用于当前用户的交互动作；项目同步和 AI 检视统一使用项目管理员配置。" />
      {loading ? (
        <SettingsConfigLoadingPanel loading error="" onRetry={loadPersonalSettings} />
      ) : (
        <div className="settings-grid">
          <article className="setting-form-card">
            <div className="setting-form-head">
              <strong>账号信息</strong>
              <span>{user?.display_name || user?.username} · {user?.global_role === "root" ? "root 管理员" : "普通用户"}</span>
            </div>
            <ConfigCard title="当前用户" rows={[`用户名 ${user?.username || "--"}`, `邮箱 ${user?.email || "--"}`, `角色 ${user?.global_role || "user"}`]} />
          </article>
          <article className="setting-form-card">
            <div className="setting-form-head">
              <strong>个人 CodeHub Token</strong>
              <span>仅用于以你的身份提交已确认的检视意见。MR 同步、diff 读取和 AI 检视统一使用项目级凭据。</span>
            </div>
            <div className="setting-form-grid">
              <SettingField label="CodeHub Token">
                <input type="password" value={vcsForm.codehub_token} onChange={(event) => setVcsForm({ ...vcsForm, codehub_token: event.target.value })} placeholder={vcsForm.codehub_token_has_value ? `已配置 ${vcsForm.codehub_token_masked}` : "输入 CodeHub Token"} />
              </SettingField>
            </div>
            <div className="setting-actions">
              <button type="button" onClick={saveVcsTokens} disabled={saving === "tokens"}>{saving === "tokens" ? "保存中..." : "保存 Token"}</button>
            </div>
          </article>
        </div>
      )}
      {successNotice && <SuccessNoticeModal notice={successNotice} onClose={() => setSuccessNotice(null)} />}
    </section>
  );
}

export function SystemSettingsWorkspace({ setMessage, canEdit }: { setMessage: (value: string) => void; canEdit: boolean }) {
  const [storage, setStorage] = useState<Record<string, unknown> | null>(null);
  const [form, setForm] = useState<StorageSettingsForm>({ postgres_url: "", postgres_user: "", postgres_password: "" });
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [initializing, setInitializing] = useState(false);
  const [notice, setNotice] = useState<SuccessNotice | null>(null);

  async function loadStorage() {
    setLoading(true);
    try {
      const result = await api<Record<string, unknown>>("/api/system/storage");
      const value = recordValue(result.value);
      setStorage(result);
      setForm({
        postgres_url: String(value.postgres_url || ""),
        postgres_user: String(value.postgres_user || ""),
        postgres_password: "",
        postgres_password_has_value: Boolean(value.postgres_password_has_value),
        postgres_password_masked: String(value.postgres_password_masked || "")
      });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadStorage().catch((error) => setMessage(error instanceof Error ? error.message : String(error)));
  }, []);

  async function testStorage() {
    setTesting(true);
    try {
      const result = await api<Record<string, unknown>>("/api/system/storage/test", {
        method: "POST",
        body: JSON.stringify(form)
      });
      const msg = String(result.message || result.status || "测试完成");
      setMessage(msg);
      setNotice({ title: Boolean(result.ok) ? "数据库配置可用" : "数据库配置未启用", message: msg });
    } finally {
      setTesting(false);
    }
  }

  async function saveStorage() {
    setSaving(true);
    try {
      const result = await api<Record<string, unknown>>("/api/system/storage/switch", {
        method: "POST",
        body: JSON.stringify(form)
      });
      setStorage(result);
      const msg = "Common 服务 PostgreSQL 运行配置已保存到 Common config.json，重启 Common 服务后生效。MR backend 和 Worker 使用各自服务的 config.json。";
      setMessage(msg);
      setNotice({ title: "Common 存储配置已保存", message: msg });
      await loadStorage();
    } finally {
      setSaving(false);
    }
  }

  async function initializePostgres() {
    setInitializing(true);
    try {
      const result = await api<Record<string, unknown>>("/api/system/storage/init-postgres", {
        method: "POST",
        body: JSON.stringify(form)
      });
      const msg = Boolean(result.ok)
        ? "PostgreSQL 初始化完成。"
        : String(result.message || "PostgreSQL 初始化失败");
      setMessage(msg);
      setNotice({ title: Boolean(result.ok) ? "PostgreSQL 初始化完成" : "PostgreSQL 初始化失败", message: msg });
    } finally {
      setInitializing(false);
    }
  }

  return (
    <section className="config-workspace">
      <ConfigHeader title="系统设置" subtitle="仅 root 管理员可维护。这里维护 Common 服务运行时配置；MR backend 和 Worker 使用各自服务配置。" />
      {loading ? (
        <SettingsConfigLoadingPanel loading error="" onRetry={loadStorage} />
      ) : (
        <div className="settings-grid">
          <article className="setting-form-card">
            <div className="setting-form-head">
              <strong>Common 数据库存储</strong>
              <span>当前实际运行：{String(storage?.current_driver || "postgres")} · {String(storage?.active_postgres_url || "--")}</span>
            </div>
            <div className="setting-form-grid">
              <SettingField label="目标数据库">
                <input value="PostgreSQL" disabled />
              </SettingField>
              <SettingField label="PG 连接串">
                <input value={form.postgres_url} onChange={(event) => setForm({ ...form, postgres_url: event.target.value })} placeholder="postgresql://host:5432/db" disabled={!canEdit} />
              </SettingField>
              <SettingField label="PG 用户名">
                <input value={form.postgres_user} onChange={(event) => setForm({ ...form, postgres_user: event.target.value })} disabled={!canEdit} />
              </SettingField>
              <SettingField label="PG 密码">
                <input type="password" value={form.postgres_password} onChange={(event) => setForm({ ...form, postgres_password: event.target.value })} placeholder={form.postgres_password_has_value ? `已配置 ${form.postgres_password_masked}` : ""} disabled={!canEdit} />
              </SettingField>
            </div>
            <div className="system-storage-note">
              系统仅支持 PostgreSQL。这里仅管理 Common 服务数据库配置；表结构初始化会真实连接目标 PG 并创建 Common 服务表/索引。保存配置会同步写入 Common config.json；当前进程不会热切断连接，重启 Common 服务后生效。
            </div>
            <div className="setting-actions">
              <button type="button" onClick={testStorage} disabled={!canEdit || testing}>{testing ? "测试中..." : "测试配置"}</button>
              <button type="button" onClick={initializePostgres} disabled={!canEdit || initializing}>{initializing ? "初始化中..." : "初始化 PG 表"}</button>
              <button type="button" onClick={saveStorage} disabled={!canEdit || saving}>{saving ? "保存中..." : "保存配置"}</button>
            </div>
          </article>
          <article className="setting-form-card">
            <div className="setting-form-head">
              <strong>权限边界</strong>
              <span>Common 数据库配置只允许 root 修改；MR backend 和 Worker 的数据库目标由各自服务 config.json 维护。</span>
            </div>
            <ConfigCard title="当前状态" rows={[
              `PG runtime ${storage?.pg_runtime_enabled ? "enabled" : "not enabled"}`,
              `切换状态 ${String(storage?.switch_status || "not_enabled")}`,
              `更新时间 ${String(storage?.updated_at || "--")}`
            ]} />
          </article>
        </div>
      )}
      {notice && <SuccessNoticeModal notice={notice} onClose={() => setNotice(null)} />}
    </section>
  );
}

export function ConfigHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="config-header">
      <h1>{title}</h1>
      <p>{subtitle}</p>
    </div>
  );
}

export function SettingField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="setting-field">
      <span>{label}</span>
      {children}
    </label>
  );
}

export function SettingsConfigLoadingPanel({
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

export function SuccessNoticeModal({ notice, onClose }: { notice: SuccessNotice; onClose: () => void }) {
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

export function StaticToolSwitchBoard({
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

export function StaticToolAvailabilityPanel({ availability }: { availability: StaticToolAvailability | null }) {
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

export function ConfigCard({ title, rows }: { title: string; rows: string[] }) {
  return (
    <article className="config-card">
      <strong>{title}</strong>
      {rows.map((row, index) => <span key={`${title}-${index}-${row ?? ""}`}>{row}</span>)}
    </article>
  );
}

export function ConfigTable({ rows, columns }: { rows: Record<string, unknown>[]; columns: string[] }) {
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

export function AgentProfileCard({
  row,
  projectId,
  ruleCount,
  toolCount,
  toolNames,
  skillNames,
  ruleDetails,
  skillDetails,
  skillAssetDetails,
  bindingOptions,
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
  toolNames: string[];
  skillNames: string[];
  ruleDetails: AgentBindingDetail[];
  skillDetails: AgentBindingDetail[];
  skillAssetDetails: AgentBindingDetail[];
  bindingOptions: AgentBindingEditorOptions;
  quality: Record<string, unknown>;
  reload: () => Promise<void>;
  setMessage: (value: string) => void;
  toggleAgent: (row: Record<string, unknown>) => Promise<void>;
  canEdit: boolean;
}) {
  const agentKey = String(row.agent_key || row.agent_id);
  const boundRuleResolutionRate = Number(quality.bound_rule_resolution_rate);
  const [roleProfile, setRoleProfile] = useState(String(row.role_profile || row.name || ""));
  const [responsibilityScope, setResponsibilityScope] = useState(String(row.responsibility_scope || ""));
  const [excludedScope, setExcludedScope] = useState(String(row.excluded_scope || ""));
  const [minConfidence, setMinConfidence] = useState(String(row.min_confidence ?? "0.75"));
  const [maxFindings, setMaxFindings] = useState(String(row.max_findings ?? "12"));
  const [maxLlmCalls, setMaxLlmCalls] = useState(String(row.max_llm_calls ?? "6"));
  const [maxToolCalls, setMaxToolCalls] = useState(String(row.max_tool_calls ?? "12"));
  const [bindingDetail, setBindingDetail] = useState<AgentBindingDetail | null>(null);
  const [bindingEditorOpen, setBindingEditorOpen] = useState(false);

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

  async function removeSkillBinding(detail: AgentBindingDetail) {
    if (!detail.bindingId) {
      setMessage("该 Skill 绑定缺少绑定 ID，请刷新后重试");
      return;
    }
    const confirmed = window.confirm(`确认从 ${String(row.display_name || agentKey)} 移除 Skill「${detail.title}」吗？Skill 包本身会保留，可重新绑定。`);
    if (!confirmed) return;
    await api(`/api/projects/${projectId}/expert-skill-bindings/${encodeURIComponent(detail.bindingId)}`, { method: "DELETE" });
    setMessage(`已移除 Skill 绑定：${detail.title}`);
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
            {ruleDetails.length
              ? ruleDetails.map((detail, index) => (
                <button
                  className="agent-binding-button"
                  type="button"
                  key={`${agentKey}-rule-${index}-${detail.title}`}
                  onClick={() => setBindingDetail(detail)}
                  title="查看规范详情"
                >
                  {detail.title}
                </button>
              ))
              : <span>未绑定规范文档</span>}
          </div>
          <div>
            <strong>绑定工具</strong>
            {(toolNames.length ? toolNames : ["未绑定工具"]).map((name, index) => <span key={`${agentKey}-tool-${index}-${name}`}>{name}</span>)}
          </div>
          <div>
            <strong>绑定 Skill</strong>
            {skillDetails.length
              ? skillDetails.map((detail, index) => (
                <div
                  className="agent-binding-item"
                  key={`${agentKey}-skill-${index}-${detail.title}`}
                >
                  <button
                    className="agent-binding-button"
                    type="button"
                    onClick={() => setBindingDetail(detail)}
                    title="查看 Skill 内容"
                  >
                    <b>{detail.title}</b>
                    <small>{detail.subtitle}</small>
                    {detail.assets?.length ? <span className="agent-binding-file-preview">{skillAssetPathPreview(detail.assets)}</span> : null}
                  </button>
                  <button
                    className="agent-binding-remove-button"
                    type="button"
                    onClick={() => { removeSkillBinding(detail).catch((error) => setMessage(error instanceof Error ? error.message : String(error))); }}
                    disabled={!canEdit}
                    title="移除这个专家的 Skill 绑定"
                    aria-label={`移除 Skill 绑定 ${detail.title}`}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))
              : <span>未绑定自定义 Skill</span>}
          </div>
          <div>
            <strong>Skill 资源</strong>
            {skillAssetDetails.length
              ? skillAssetDetails.map((detail, index) => (
                <button
                  className="agent-binding-button"
                  type="button"
                  key={`${agentKey}-asset-${index}-${detail.subtitle}-${detail.title}`}
                  onClick={() => setBindingDetail(detail)}
                  title="查看 Skill 资源内容"
                >
                  {detail.subtitle}/{detail.title}
                </button>
              ))
              : <span>未绑定 Skill 资源</span>}
          </div>
        </div>
        <div className="agent-metrics-line">
          <span>规则 {ruleCount}</span>
          <span>Skill {skillNames.length}</span>
          <span>工具 {toolCount}</span>
          <span>问题 {String(quality.finding_count ?? 0)}</span>
          <span>误报率 {String(quality.false_positive_rate ?? "--")}</span>
          <span>规则闭环 {Number.isFinite(boundRuleResolutionRate) ? `${Math.round(boundRuleResolutionRate * 100)}%` : "--"}</span>
          <span>未闭环 {String(quality.bound_rule_unresolved_count ?? 0)}</span>
        </div>
      </div>
      <div className="agent-card-actions">
        <button type="button" onClick={() => toggleAgent(row)} disabled={!canEdit}>{Boolean(row.enabled) ? "停用" : "启用"}</button>
        <button type="button" onClick={() => setBindingEditorOpen(true)} disabled={!canEdit}>编辑绑定</button>
        <button type="button" onClick={saveProfile} disabled={!canEdit}>保存</button>
      </div>
      {bindingDetail && <AgentBindingDetailModal detail={bindingDetail} onClose={() => setBindingDetail(null)} />}
      {bindingEditorOpen && (
        <AgentBindingEditorModal
          projectId={projectId}
          agentKey={agentKey}
          agentName={String(row.display_name || agentKey)}
          row={row}
          options={bindingOptions}
          onClose={() => setBindingEditorOpen(false)}
          onSaved={async () => {
            setBindingEditorOpen(false);
            setMessage("专家绑定已保存");
            await reload();
          }}
        />
      )}
    </article>
  );
}

export function AgentBindingEditorModal({
  projectId,
  agentKey,
  agentName,
  row,
  options,
  onClose,
  onSaved
}: {
  projectId: string;
  agentKey: string;
  agentName: string;
  row: Record<string, unknown>;
  options: AgentBindingEditorOptions;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const existingRuleBindings = options.ruleBindings.filter((binding) => String(binding.agent_key) === agentKey);
  const existingRuleIds = new Set(existingRuleBindings.map((binding) => String(binding.rule_document_id)));
  const existingSkillBindings = options.skillBindings.filter((binding) => String(binding.agent_key) === agentKey);
  const existingSkillKeys = new Set(existingSkillBindings.filter((binding) => Boolean(binding.enabled)).map((binding) => String(binding.skill_key)));
  const existingToolBindings = options.toolBindings.filter((binding) => String(binding.agent_key) === agentKey);
  const existingToolNames = new Set(existingToolBindings.filter((binding) => Boolean(binding.enabled)).map((binding) => String(binding.tool_name)));
  const agentTools = parseJsonArray(typeof row.tools_json === "string" ? row.tools_json : undefined);
  const availabilityTools = (options.staticToolAvailability?.items ?? []).map((item) => item.name);
  const toolCandidates = Array.from(new Set([
    ...STATIC_TOOL_SWITCHES.flatMap((tool) => [tool.key, tool.availabilityName]),
    ...availabilityTools,
    ...agentTools,
    ...existingToolBindings.map((binding) => String(binding.tool_name))
  ].filter(Boolean))).sort((left, right) => left.localeCompare(right));
  const [selectedRuleIds, setSelectedRuleIds] = useState(() => new Set(existingRuleIds));
  const [selectedSkillKeys, setSelectedSkillKeys] = useState(() => new Set(existingSkillKeys));
  const [selectedToolNames, setSelectedToolNames] = useState(() => new Set(existingToolNames));
  const [newRuleName, setNewRuleName] = useState("");
  const [newRuleContent, setNewRuleContent] = useState("");
  const [newSkillName, setNewSkillName] = useState("");
  const [newSkillKey, setNewSkillKey] = useState("");
  const [newSkillContent, setNewSkillContent] = useState("");
  const [newRuleFileInfo, setNewRuleFileInfo] = useState("");
  const [newSkillBundleFiles, setNewSkillBundleFiles] = useState<File[]>([]);
  const [newSkillBundleInfo, setNewSkillBundleInfo] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function applyModalRuleTemplate() {
    setNewRuleName(RULE_DOCUMENT_TEMPLATE_NAME);
    setNewRuleContent(RULE_DOCUMENT_TEMPLATE);
    setNewRuleFileInfo("已填入规范模板，可按团队规则修改");
    setError("");
  }

  function applyModalSkillTemplate() {
    setNewSkillName(SKILL_TEMPLATE_NAME);
    setNewSkillKey(SKILL_TEMPLATE_KEY);
    setNewSkillContent(SKILL_MD_TEMPLATE);
    setNewSkillBundleFiles([]);
    setNewSkillBundleInfo("已填入 SKILL.md 和 references/security-review-rules.md 模板");
    setError("");
  }

  function assetsForSkill(skillKey: string) {
    return options.skillAssets
      .filter((asset) => String(asset.skill_key) === skillKey)
      .sort((left, right) => String(left.asset_path || "").localeCompare(String(right.asset_path || "")));
  }

  function toggleSet(setter: React.Dispatch<React.SetStateAction<Set<string>>>, value: string, checked: boolean) {
    setter((current) => {
      const next = new Set(current);
      if (checked) next.add(value);
      else next.delete(value);
      return next;
    });
  }

  async function createAndBindRuleDocument() {
    const name = newRuleName.trim();
    const content = newRuleContent.trim();
    if (!name || !content) {
      setError("请填写规范名称和规范内容");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const document = await api<Record<string, unknown>>(`/api/projects/${projectId}/rule-documents`, {
        method: "POST",
        body: JSON.stringify({
          name,
          doc_type: "markdown",
          content,
          version: "v1",
          status: "active"
        })
      });
      const ruleDocumentId = String(document.id || "");
      if (!ruleDocumentId) throw new Error("规范文档创建失败：未返回文档 ID");
      await api(`/api/projects/${projectId}/expert-rule-bindings`, {
        method: "POST",
        body: JSON.stringify({ agent_key: agentKey, rule_document_id: ruleDocumentId, priority: 100 })
      });
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function handleModalRuleMarkdownFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".md")) {
      setError("请选择 .md 格式的规范文档");
      return;
    }
    setError("");
    setNewRuleName(file.name);
    setNewRuleContent(await readUploadText(file));
    setNewRuleFileInfo(`${file.name} · ${readableFileSize(file.size)}`);
  }

  async function createAndBindCustomSkill() {
    if (newSkillBundleFiles.length) {
      setSaving(true);
      setError("");
      try {
        await uploadSkillBundleToProject({
          projectId,
          agentKey,
          skillName: newSkillName,
          skillKey: newSkillKey,
          files: newSkillBundleFiles
        });
        await onSaved();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setSaving(false);
      }
      return;
    }
    const name = newSkillName.trim();
    const content = newSkillContent.trim();
    if (!name || !content) {
      setError("请填写 Skill 名称和 Skill 内容");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const templateAssets = skillReferenceTemplateAssets(content);
      const validation = await validateSkillBundle({ projectId, skillName: name, skillKey: newSkillKey, content, assets: templateAssets });
      if (!validation.ok) {
        setError(formatValidationFailures(validation));
        setSaving(false);
        return;
      }
      const skill = await api<Record<string, unknown>>(`/api/projects/${projectId}/custom-skills`, {
        method: "POST",
        body: JSON.stringify({
          skill_key: newSkillKey.trim() || name,
          name,
          description: "通过专家绑定弹窗上传的自定义 Skill",
          content,
          version: "v1",
          status: "active"
        })
      });
      const createdSkillKey = String(skill.skill_key || newSkillKey.trim() || name);
      await api(`/api/projects/${projectId}/custom-skill-assets`, {
        method: "POST",
        body: JSON.stringify({
          skill_key: createdSkillKey,
          asset_path: "SKILL.md",
          asset_type: "skill",
          content,
          executable: false
        })
      });
      for (const asset of templateAssets) {
        await api(`/api/projects/${projectId}/custom-skill-assets`, {
          method: "POST",
          body: JSON.stringify({
            skill_key: createdSkillKey,
            asset_path: asset.asset_path,
            asset_type: "reference",
            content: asset.content,
            executable: false
          })
        });
      }
      await api(`/api/projects/${projectId}/expert-skill-bindings`, {
        method: "POST",
        body: JSON.stringify({ agent_key: agentKey, skill_key: createdSkillKey, priority: 100, enabled: true })
      });
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  function handleModalSkillBundleFiles(event: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!files.length) return;
    const rootName = skillRootNameFromFiles(files);
    if (rootName && !newSkillName.trim()) setNewSkillName(rootName);
    if (rootName && !newSkillKey.trim()) setNewSkillKey(rootName);
    const totalSize = files.reduce((sum, file) => sum + file.size, 0);
    const assetPaths = files
      .map(normalizeSkillBundleAssetPath)
      .filter((path) => path && !path.includes("..") && isStandardSkillAssetPath(path));
    const hasSkillMd = assetPaths.some((path) => path === "SKILL.md");
    setNewSkillBundleFiles(files);
    setNewSkillBundleInfo(`${rootName || "已选择文件"} · 有效资源 ${assetPaths.length}/${files.length} 个 · ${readableFileSize(totalSize)}${hasSkillMd ? "" : " · 缺少 SKILL.md"}`);
    setError(hasSkillMd ? "" : "Skill 文件夹缺少 SKILL.md");
  }

  async function saveBindings() {
    setSaving(true);
    setError("");
    try {
      for (const rule of options.ruleDocs) {
        const ruleId = String(rule.id || "");
        if (!ruleId) continue;
        const currentlyBound = existingRuleIds.has(ruleId);
        const shouldBind = selectedRuleIds.has(ruleId);
        if (shouldBind && !currentlyBound) {
          await api(`/api/projects/${projectId}/expert-rule-bindings`, {
            method: "POST",
            body: JSON.stringify({ agent_key: agentKey, rule_document_id: ruleId, priority: 100 })
          });
        }
        if (!shouldBind && currentlyBound) {
          const binding = existingRuleBindings.find((item) => String(item.rule_document_id) === ruleId);
          if (binding?.id) {
            await api(`/api/projects/${projectId}/expert-rule-bindings/${encodeURIComponent(String(binding.id))}`, { method: "DELETE" });
          }
        }
      }
      for (const skill of options.customSkills) {
        const skillKey = String(skill.skill_key || "");
        if (!skillKey) continue;
        const currentlyBound = existingSkillBindings.some((binding) => String(binding.skill_key) === skillKey);
        const shouldBind = selectedSkillKeys.has(skillKey);
        if (shouldBind) {
          await api(`/api/projects/${projectId}/expert-skill-bindings`, {
            method: "POST",
            body: JSON.stringify({ agent_key: agentKey, skill_key: skillKey, priority: 100, enabled: true })
          });
        }
        if (!shouldBind && currentlyBound) {
          const binding = existingSkillBindings.find((item) => String(item.skill_key) === skillKey);
          if (binding?.id) {
            await api(`/api/projects/${projectId}/expert-skill-bindings/${encodeURIComponent(String(binding.id))}`, { method: "DELETE" });
          }
        }
      }
      for (const toolName of toolCandidates) {
        const currentlyBound = existingToolBindings.some((binding) => String(binding.tool_name) === toolName);
        const shouldBind = selectedToolNames.has(toolName);
        if (shouldBind || currentlyBound) {
          await api(`/api/projects/${projectId}/expert-tool-bindings`, {
            method: "POST",
            body: JSON.stringify({ agent_key: agentKey, tool_name: toolName, permission_level: "read_only", max_calls: 5, enabled: shouldBind })
          });
        }
      }
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="编辑专家绑定" onClick={onClose}>
      <section className="agent-binding-editor-modal" onClick={(event) => event.stopPropagation()}>
        <header>
          <div>
            <span>专家绑定</span>
            <strong>{agentName}</strong>
            <p>{agentKey}</p>
          </div>
          <button type="button" className="modal-close-button" onClick={onClose} aria-label="关闭编辑">
            <X size={18} />
          </button>
        </header>
        {error && <div className="agent-binding-editor-error">{error}</div>}
        <div className="agent-binding-upload-grid">
          <div className="agent-binding-upload-panel">
            <strong>上传 Markdown 规范</strong>
            <div className="template-action-row">
              <button type="button" onClick={applyModalRuleTemplate} disabled={saving}>
                <ClipboardList size={14} />
                使用规范模板
              </button>
              <a href="/templates/rule-document-template.md" target="_blank" rel="noreferrer">查看模板文件</a>
            </div>
            <label className="file-upload-dropzone compact">
              <FileCode2 size={18} />
              <span>{newRuleFileInfo || "选择 .md 文件"}</span>
              <input type="file" accept=".md,text/markdown,text/plain" onChange={handleModalRuleMarkdownFile} disabled={saving} />
            </label>
            <label>
              <span>规范名称</span>
              <input value={newRuleName} onChange={(event) => setNewRuleName(event.target.value)} placeholder="例如：聚合根设计规范" disabled={saving} />
            </label>
            <details className="compact-preview">
              <summary>查看或微调规范内容</summary>
              <textarea value={newRuleContent} onChange={(event) => setNewRuleContent(event.target.value)} placeholder="# 规范标题&#10;&#10;写入判断标准、违规示例和修复建议。" disabled={saving} />
            </details>
            <button type="button" onClick={createAndBindRuleDocument} disabled={saving}>{saving ? "处理中..." : "上传并绑定规范"}</button>
          </div>
          <div className="agent-binding-upload-panel">
            <strong>上传 Skill 文件夹</strong>
            <div className="template-action-row">
              <button type="button" onClick={applyModalSkillTemplate} disabled={saving}>
                <ClipboardList size={14} />
                使用 Skill 模板
              </button>
              <a href="/templates/security-review-skill-template/SKILL.md" target="_blank" rel="noreferrer">SKILL.md</a>
              <a href="/templates/security-review-skill-template/references/security-review-rules.md" target="_blank" rel="noreferrer">references 规范</a>
            </div>
            <label className="file-upload-dropzone compact">
              <Folder size={18} />
              <span>{newSkillBundleInfo || "选择包含 SKILL.md 的文件夹"}</span>
              <input
                type="file"
                multiple
                ref={(node) => {
                  if (node) {
                    node.setAttribute("webkitdirectory", "");
                    node.setAttribute("directory", "");
                  }
                }}
                onChange={handleModalSkillBundleFiles}
                disabled={saving}
              />
            </label>
            <label>
              <span>Skill 名称</span>
              <input value={newSkillName} onChange={(event) => setNewSkillName(event.target.value)} placeholder="例如：领域建模深度检查" disabled={saving} />
            </label>
            <label>
              <span>Skill Key</span>
              <input value={newSkillKey} onChange={(event) => setNewSkillKey(event.target.value)} placeholder="可选，留空会按名称生成" disabled={saving} />
            </label>
            <details className="compact-preview">
              <summary>手动填写 SKILL.md</summary>
              <textarea value={newSkillContent} onChange={(event) => setNewSkillContent(event.target.value)} placeholder="# Skill 说明&#10;&#10;写入专家执行步骤、输入证据和输出要求。" disabled={saving} />
            </details>
            <button type="button" onClick={createAndBindCustomSkill} disabled={saving}>{saving ? "处理中..." : newSkillBundleFiles.length ? "上传并绑定文件夹" : "创建并绑定 Skill"}</button>
          </div>
        </div>
        <div className="agent-binding-editor-columns">
          <AgentBindingChecklist
            title="规范文档"
            emptyText="暂无可绑定规范文档"
            items={options.ruleDocs.map((rule) => ({
              id: String(rule.id || ""),
              title: String(rule.name || rule.id || "未命名规范"),
              description: `${String(rule.version || "v1")} · ${String(rule.status || "draft")}`
            }))}
            selected={selectedRuleIds}
            onToggle={(id, checked) => toggleSet(setSelectedRuleIds, id, checked)}
          />
          <AgentBindingChecklist
            title="静态工具"
            emptyText="暂无可绑定工具"
            items={toolCandidates.map((name) => {
              const tool = STATIC_TOOL_SWITCHES.find((item) => item.key === name || item.availabilityName === name);
              return {
                id: name,
                title: tool?.displayName || name,
                description: tool ? `${tool.category} · ${tool.requiredFor}` : "项目工具绑定"
              };
            })}
            selected={selectedToolNames}
            onToggle={(id, checked) => toggleSet(setSelectedToolNames, id, checked)}
          />
          <AgentBindingChecklist
            title="自定义 Skill"
            emptyText="暂无可绑定 Skill"
            items={options.customSkills.map((skill) => {
              const currentSkillKey = String(skill.skill_key || "");
              const assets = assetsForSkill(currentSkillKey);
              return {
                id: currentSkillKey,
                title: String(skill.name || skill.skill_key || "未命名 Skill"),
                description: `${String(skill.description || skill.version || "custom skill")} · ${skillAssetSummary(assets)}`,
                detail: assets.length ? skillAssetManifest(assets) : ""
              };
            })}
            selected={selectedSkillKeys}
            onToggle={(id, checked) => toggleSet(setSelectedSkillKeys, id, checked)}
          />
        </div>
        <footer>
          <button type="button" className="secondary" onClick={onClose} disabled={saving}>取消</button>
          <button type="button" onClick={saveBindings} disabled={saving}>{saving ? "保存中..." : "保存绑定"}</button>
        </footer>
      </section>
    </div>
  );
}

export function AgentBindingChecklist({
  title,
  emptyText,
  items,
  selected,
  onToggle
}: {
  title: string;
  emptyText: string;
  items: Array<{ id: string; title: string; description: string; detail?: string }>;
  selected: Set<string>;
  onToggle: (id: string, checked: boolean) => void;
}) {
  const validItems = items.filter((item) => item.id);
  return (
    <div className="agent-binding-checklist">
      <strong>{title}</strong>
      <div>
        {validItems.map((item) => (
          <label key={item.id}>
            <input type="checkbox" checked={selected.has(item.id)} onChange={(event) => onToggle(item.id, event.target.checked)} />
            <span>
              <b>{item.title}</b>
              <em>{item.description}</em>
              {item.detail && <p>{item.detail}</p>}
            </span>
          </label>
        ))}
        {!validItems.length && <p>{emptyText}</p>}
      </div>
    </div>
  );
}

export function AgentBindingDetailModal({ detail, onClose }: { detail: AgentBindingDetail; onClose: () => void }) {
  const kindLabel = detail.kind === "rule" ? "规范文档" : detail.kind === "skill" ? "Skill" : "Skill 资源";
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={`${kindLabel}详情`} onClick={onClose}>
      <section className="agent-binding-modal" onClick={(event) => event.stopPropagation()}>
        <header>
          <div>
            <span>{kindLabel}</span>
            <strong>{detail.title}</strong>
            <p>{detail.subtitle}</p>
          </div>
          <button type="button" className="modal-close-button" onClick={onClose} aria-label="关闭详情">
            <X size={18} />
          </button>
        </header>
        <div className="agent-binding-meta">
          {detail.metadata.map(([label, value]) => (
            <p key={`${label}-${value}`}>
              <span>{label}</span>
              <strong>{value}</strong>
            </p>
          ))}
        </div>
        {detail.assets?.length ? (
          <div className="agent-binding-asset-manifest">
            <strong>Bundle 文件</strong>
            <div>
              {detail.assets.map((asset) => (
                <span key={`${asset.path}-${asset.type}`}>
                  <b>{asset.path}</b>
                  <em>{asset.type}{asset.executable ? " · 可执行" : ""}</em>
                </span>
              ))}
            </div>
          </div>
        ) : null}
        <pre className="agent-binding-content">{detail.content || "暂无内容"}</pre>
      </section>
    </div>
  );
}
