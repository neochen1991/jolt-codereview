import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { badRequest, id, notFound, route, sha1, type Route } from "../http.js";
import { normalizeRepoConfig, postIssueComment } from "../github.js";
import { postCodeHubSummaryComment } from "../codehub.js";
import type { AppConfig, FindingRow, MergeRequestRow, RepositoryConfig } from "../types.js";
import type { Db } from "../db.js";
import { AgentRepository } from "../repositories/AgentRepository.js";
import { AuditRepository } from "../repositories/AuditRepository.js";
import { MergeRequestRepository } from "../repositories/MergeRequestRepository.js";
import { ProjectRepository } from "../repositories/ProjectRepository.js";
import { RepositoryRepository } from "../repositories/RepositoryRepository.js";
import { ReviewJobRepository } from "../repositories/ReviewJobRepository.js";
import { RuleDocumentRepository } from "../repositories/RuleDocumentRepository.js";
import { AgentConfigService } from "../services/AgentConfigService.js";
import { AgentToolBindingService } from "../services/AgentToolBindingService.js";
import { FeedbackLearningService } from "../services/FeedbackLearningService.js";
import { MrSyncService } from "../services/MrSyncService.js";
import { ObservabilityService } from "../services/ObservabilityService.js";
import { ProjectConfigService } from "../services/ProjectConfigService.js";
import { ReviewQueueService } from "../services/ReviewQueueService.js";
import { StaticToolAvailabilityService } from "../services/StaticToolAvailabilityService.js";
import { queuedReviewWorkerCapacity } from "../services/WorkerLaunchPolicy.js";
import { spawnWorkerOnce as launchWorkerOnce, type WorkerProcessLogger } from "../services/WorkerProcessLauncher.js";

import type { BackendRouteContext } from "./context.js";
import { createAgentRoutes } from "./agents.routes.js";
import { createAuthRoutes } from "./auth.routes.js";
import { createFullReviewRoutes } from "./full-review.routes.js";
import { createHealthRoutes } from "./health.routes.js";
import { createObservabilityRoutes } from "./observability.routes.js";
import { createProjectRoutes } from "./projects.routes.js";
import { createQualityRoutes } from "./quality.routes.js";
import { createRepositoryRoutes } from "./repositories.routes.js";
import { createReviewRoutes } from "./review.routes.js";
import { createRuleRoutes } from "./rules.routes.js";
import { createSystemRoutes } from "./system.routes.js";
import { createVcsProxyRoutes } from "./vcs-proxy.routes.js";
import { createWebhookRoutes } from "./webhooks.routes.js";
export function createRoutes(config: AppConfig, db: Db, logger?: WorkerProcessLogger): Route[] {
  const projectRepository = new ProjectRepository(db);
  const repositoryRepository = new RepositoryRepository(db);
  const mergeRequestRepository = new MergeRequestRepository(db);
  const reviewJobRepository = new ReviewJobRepository(db);
  const agentRepository = new AgentRepository(db);
  const ruleDocumentRepository = new RuleDocumentRepository(db);
  const auditRepository = new AuditRepository(db);
  const agentConfigService = new AgentConfigService(agentRepository);
  const agentToolBindingService = new AgentToolBindingService(db);
  const feedbackLearningService = new FeedbackLearningService(db);
  const projectConfigService = new ProjectConfigService(db);
  const reviewQueueService = new ReviewQueueService(reviewJobRepository);
  const mrSyncService = new MrSyncService(config, repositoryRepository, mergeRequestRepository, reviewQueueService, runWorkerOnce, projectConfigService);
  const observabilityService = new ObservabilityService(db);
  const staticToolAvailabilityService = new StaticToolAvailabilityService();

  function all<T>(sql: string, params: any[] = []): T[] {
    return db.prepare(sql).all(...params) as T[];
  }
  
  function get<T>(sql: string, params: any[] = []): T | undefined {
    return db.prepare(sql).get(...params) as T | undefined;
  }
  
  function spawnWorkerOnce() {
    launchWorkerOnce(logger);
  }

  function runWorkerOnce() {
    const count = queuedReviewWorkerCapacity({ config, db, projectConfigService });
    const spawnCount = Math.max(1, count);
    for (let index = 0; index < spawnCount; index += 1) {
      spawnWorkerOnce();
    }
  }
  
  function repoConfig(row: { provider_config_json: string }): RepositoryConfig {
    return normalizeRepoConfig(JSON.parse(row.provider_config_json || "{}"));
  }
  
  function riskScore(pull: { additions?: number; deletions?: number; changed_files?: number }): number {
    const churn = (pull.additions ?? 0) + (pull.deletions ?? 0);
    return Math.min(100, Math.round((pull.changed_files ?? 0) * 8 + churn / 35));
  }
  
  function timingSafeEquals(a: string, b: string): boolean {
    const left = Buffer.from(a);
    const right = Buffer.from(b);
    return left.length === right.length && timingSafeEqual(left, right);
  }
  
  function verifyGitHubSignature(secret: string | undefined, rawBody: string, signature: string | null): boolean {
    if (!secret) return true;
    if (!signature?.startsWith("sha256=")) return false;
    const expected = `sha256=${createHmac("sha256", secret).update(rawBody).digest("hex")}`;
    return timingSafeEquals(expected, signature);
  }
  
  function verifyCodeHubSignature(secret: string | undefined, rawBody: string, signature: string | null): boolean {
    if (!secret) return true;
    if (!signature) return false;
    const normalized = signature.startsWith("sha256=") ? signature : `sha256=${signature}`;
    const expected = `sha256=${createHmac("sha256", secret).update(rawBody).digest("hex")}`;
    return timingSafeEquals(expected, normalized);
  }
  
  function firstString(...values: unknown[]): string {
    for (const value of values) {
      if (value !== undefined && value !== null && String(value).trim()) return String(value);
    }
    return "";
  }
  
  function firstNumber(...values: unknown[]): number {
    for (const value of values) {
      const number = Number(value);
      if (Number.isFinite(number) && number > 0) return number;
    }
    return 0;
  }
  
  function nestedValue(source: Record<string, any>, path: string): unknown {
    return path.split(".").reduce<unknown>((current, key) => {
      if (!current || typeof current !== "object") return undefined;
      return (current as Record<string, unknown>)[key];
    }, source);
  }
  
  function normalizeCodeHubWebhookPayload(payload: Record<string, any>) {
    const mr = (
      payload.merge_request ??
      payload.pull_request ??
      payload.object_attributes ??
      payload.mr ??
      nestedValue(payload, "event.merge_request") ??
      payload
    ) as Record<string, any>;
    const repository = (
      payload.repository ??
      payload.project ??
      payload.repo ??
      nestedValue(payload, "event.repository") ??
      {}
    ) as Record<string, any>;
    const author = mr.author ?? payload.user ?? payload.sender ?? {};
    const repoFullName = firstString(
      repository.full_name,
      repository.name_with_namespace,
      repository.path_with_namespace,
      repository.fullName,
      repository.path,
      payload.repository_full_name,
      payload.repo_id,
      mr.repository_full_name
    );
    const action = firstString(payload.action, payload.event_type, payload.object_kind, payload.event_name, mr.action, mr.state, "updated").toLowerCase();
    const headSha = firstString(
      mr.head_sha,
      mr.sha,
      mr.last_commit?.id,
      mr.last_commit?.sha,
      mr.source_sha,
      payload.head_sha,
      payload.after
    );
    return {
      action,
      repoFullName,
      externalId: firstString(mr.id, mr.iid, mr.number, mr.merge_request_id, mr.mr_id),
      number: firstNumber(mr.iid, mr.number, mr.id, mr.merge_request_id, mr.mr_id),
      title: firstString(mr.title, mr.name, payload.title),
      author: firstString(author.username, author.name, author.login, author.display_name, payload.user_name),
      sourceBranch: firstString(mr.source_branch, mr.source?.branch, mr.head?.ref, payload.source_branch),
      targetBranch: firstString(mr.target_branch, mr.target?.branch, mr.base?.ref, payload.target_branch),
      headSha,
      htmlUrl: firstString(mr.web_url, mr.html_url, mr.url, payload.web_url),
      state: firstString(mr.state, payload.state).toLowerCase(),
      additions: firstNumber(mr.additions, payload.additions),
      deletions: firstNumber(mr.deletions, payload.deletions),
      changedFiles: firstNumber(mr.changed_files, mr.changedFiles, payload.changed_files)
    };
  }
  
  function codehubRepoMatches(row: { external_repo_id: string; provider_config_json: string }, repoFullName: string): boolean {
    const configValue = repoConfig(row);
    const candidates = new Set(
      [
        row.external_repo_id,
        configValue.git_url,
        configValue.full_name,
        configValue.repo_id,
        configValue.repo,
        configValue.project_key && configValue.repo ? `${configValue.project_key}/${configValue.repo}` : ""
      ].filter(Boolean)
    );
    return Boolean(repoFullName && candidates.has(repoFullName));
  }

  function effectiveConfigForUser(userId?: string | null): AppConfig {
    if (!userId) return config;
    const rows = projectRepository.listUserSettings(userId) as Array<{ settings_key: string; settings_json: string }>;
    const tokenSettings = rows.find((row) => row.settings_key === "vcs_tokens");
    if (!tokenSettings) return config;
    const tokens = JSON.parse(tokenSettings.settings_json || "{}") as Record<string, unknown>;
    const githubToken = String(tokens.github_token || "").trim();
    const codehubToken = String(tokens.codehub_token || "").trim();
    if (!githubToken && !codehubToken) return config;
    return {
      ...config,
      github: {
        ...config.github,
        ...(githubToken ? { default_token: githubToken } : {})
      },
      codehub: {
        ...config.codehub,
        ...(codehubToken ? { default_token: codehubToken } : {})
      }
    };
  }
  
  function projectRoleRank(role: string): number {
    return { system_admin: 5, project_admin: 4, reviewer: 3, developer: 2, observer: 1 }[role] ?? 0;
  }
  
  function bearerToken(req: { headers: Record<string, any> }) {
    const value = Array.isArray(req.headers.authorization) ? req.headers.authorization[0] : req.headers.authorization;
    if (!value?.startsWith("Bearer ")) return null;
    return value.slice("Bearer ".length).trim();
  }
  
  function currentUserId(req: { headers: Record<string, any> }) {
    const token = bearerToken(req);
    if (token) {
      const session = projectRepository.findSessionUserId(sha1(token)) as { user_id: string } | undefined;
      if (session) return session.user_id;
    }
    if (process.env.JOLT_TRUST_X_USER_ID === "1" || process.env.JOLT_TRUST_X_USER_ID === "true") {
      const headerUser = Array.isArray(req.headers["x-user-id"]) ? req.headers["x-user-id"][0] : req.headers["x-user-id"];
      return headerUser ? String(headerUser) : "";
    }
    return "";
  }
  
  function ensureProjectRole(projectId: string, userId: string, minRole: string) {
    if (!userId) return { statusCode: 401, error: "unauthorized", message: "login is required" };
    if (projectRepository.isRoot(userId)) return null;
    const member = projectRepository.findMemberRole(projectId, userId) as { role: string } | undefined;
    if (!member || projectRoleRank(member.role) < projectRoleRank(minRole)) {
      return { statusCode: 403, error: "forbidden", message: `${minRole} permission is required` };
    }
    return null;
  }
  
  function ensureProjectWrite(projectId: string, userId = "") {
    return ensureProjectRole(projectId, userId, "project_admin");
  }

  function ensureRoot(userId: string) {
    if (!userId) return { statusCode: 401, error: "unauthorized", message: "login is required" };
    if (!projectRepository.isRoot(userId)) {
      return { statusCode: 403, error: "forbidden", message: "root permission is required" };
    }
    return null;
  }
  
  function auditLog(input: {
    userId?: string;
    projectId?: string;
    action: string;
    resourceType: string;
    resourceId?: string;
    summary?: string;
    metadata?: Record<string, unknown>;
  }) {
    auditRepository.record({
      id: id("audit"),
      userId: input.userId ?? null,
      projectId: input.projectId ?? null,
      action: input.action,
      resourceType: input.resourceType,
      resourceId: input.resourceId ?? null,
      summary: input.summary ?? "",
      metadata: input.metadata ?? {}
    });
  }
  
  async function syncProject(projectId: string, requestedBy?: string | null) {
    return mrSyncService.syncProject(projectId, requestedBy);
  }
  
  function canUseGithubSuggestion(finding: FindingRow) {
    const suggested = String(finding.suggested_code ?? "").trim();
    if (!suggested) return false;
    if (!finding.line_start) return false;
    const span = Math.max(1, Number(finding.line_end || finding.line_start) - Number(finding.line_start) + 1);
    return span <= 30;
  }

  function appendSuggestedCode(lines: string[], finding: FindingRow, provider: string) {
    const suggested = String(finding.suggested_code ?? "").trim();
    if (!suggested) return;
    if (provider === "github" && canUseGithubSuggestion(finding)) {
      lines.push("  - 建议修改代码：");
      lines.push("```suggestion");
      lines.push(suggested);
      lines.push("```");
      return;
    }
    lines.push("  - 建议修改代码：");
    lines.push("```");
    lines.push(suggested);
    lines.push("```");
  }

  function formatPublishBody(mr: MergeRequestRow, findings: FindingRow[], provider = "github") {
    const lines = [
      "## Jolt AI Code Review",
      "",
      `本次人工确认提交 ${findings.length} 条 AI 检视意见。`,
      ""
    ];
    for (const finding of findings) {
      const location = formatFindingLocation(finding);
      lines.push(`- [${finding.severity}] ${finding.title}`);
      lines.push(`  - 位置：${location}`);
      lines.push(`  - 说明：${finding.problem_description}`);
      lines.push(`  - 建议：${finding.recommendation}`);
      appendSuggestedCode(lines, finding, provider);
    }
    lines.push("", `关联 head_sha: ${mr.latest_head_sha}`);
    return lines.join("\n");
  }

  function formatFindingLocation(finding: FindingRow) {
    if (!finding.line_start) return finding.file_path;
    if (finding.line_end && finding.line_end !== finding.line_start) {
      return `${finding.file_path}:${finding.line_start}-${finding.line_end}`;
    }
    return `${finding.file_path}:${finding.line_start}`;
  }
  
  async function publishFindings(mrId: string, findingIds: string[], dryRun: boolean, userId = "user_local_admin") {
    const mr = mergeRequestRepository.findById(mrId);
    if (!mr) return notFound();
    const repo = repositoryRepository.findById(mr.repository_id) as { id: string; project_id: string; provider: string; provider_config_json: string } | undefined;
    if (!repo) return notFound();
    const denied = ensureProjectRole(repo.project_id, userId, "reviewer");
    if (denied) return denied;
    const requestedFindingIds = Array.from(new Set(findingIds.filter(Boolean)));
    if (requestedFindingIds.length === 0) return badRequest("finding_ids is required");
    const placeholders = requestedFindingIds.map(() => "?").join(",");
    const findings = all<FindingRow>(`SELECT * FROM review_findings WHERE id IN (${placeholders})`, requestedFindingIds);
    if (!findings.length) return badRequest("no publishable findings");
    const publishedRecords = dryRun
      ? []
      : all<{ finding_id: string }>(
        `SELECT DISTINCT finding_id FROM vcs_publish_records WHERE finding_id IN (${placeholders}) AND publish_status = 'published'`,
        requestedFindingIds
      );
    const publishedRecordIds = new Set(publishedRecords.map((record) => record.finding_id));
    const skippedFindingIds = dryRun
      ? []
      : findings
        .filter((finding) => finding.publish_state === "published" || publishedRecordIds.has(finding.id))
        .map((finding) => finding.id);
    const skippedFindingIdSet = new Set(skippedFindingIds);
    const publishableFindings = dryRun ? findings : findings.filter((finding) => !skippedFindingIdSet.has(finding.id));
    const body = publishableFindings.length ? formatPublishBody(mr, publishableFindings, repo.provider) : "";
    let commentRef = body ? `dry_run_${sha1(body).slice(0, 10)}` : "";
  
    if (!dryRun && publishableFindings.length > 0) {
      const publishConfig = effectiveConfigForUser(userId);
      const ref = repo.provider === "github"
        ? await postIssueComment(publishConfig, repoConfig(repo), mr.number, body)
        : await postCodeHubSummaryComment(publishConfig, repoConfig(repo), mr.number, body);
      commentRef = ref.id;
    }
  
    for (const finding of publishableFindings) {
      const publishId = id("pub");
      db.prepare(`
        INSERT INTO vcs_publish_records (
          id, finding_id, provider, external_comment_id, external_thread_id, publish_status, published_by, body
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      `).run(publishId, finding.id, repo.provider, commentRef, commentRef, dryRun ? "dry_run" : "published", userId, body);
      db.prepare("UPDATE review_findings SET publish_state = ?, lifecycle_state = 'accepted' WHERE id = ?")
        .run(dryRun ? "dry_run" : "published", finding.id);
      feedbackLearningService.recordFeedback({
        userId,
        finding,
        feedbackType: "accepted",
        scope: "project",
        reason: dryRun ? "dry_run_publish_confirmation" : "published_to_vcs"
      });
    }
  
    if (dryRun || publishableFindings.length > 0) {
      mergeRequestRepository.updateReviewStatus(mrId, dryRun ? "waiting_confirmation" : "submitted");
    }
    auditLog({
      userId,
      projectId: repo.project_id,
      action: dryRun ? "mr_review.publish.dry_run" : "mr_review.publish",
      resourceType: "merge_request",
      resourceId: mrId,
      summary: `${dryRun ? "Dry-run" : "Published"} ${publishableFindings.length} findings to ${repo.provider}`,
      metadata: {
        finding_ids: requestedFindingIds,
        published_finding_ids: publishableFindings.map((finding) => finding.id),
        skipped_finding_ids: skippedFindingIds,
        provider: repo.provider,
        comment_ref: commentRef
      }
    });
    return {
      comment_ref: commentRef,
      dry_run: dryRun,
      body,
      published_count: publishableFindings.length,
      skipped_count: skippedFindingIds.length,
      skipped_finding_ids: skippedFindingIds,
      message: skippedFindingIds.length ? "已提交的问题不会重复提交，本次已自动跳过。" : ""
    };
  }
  const ctx: BackendRouteContext = {
    config,
    db,
    projectRepository,
    repositoryRepository,
    mergeRequestRepository,
    reviewJobRepository,
    agentRepository,
    ruleDocumentRepository,
    auditRepository,
    agentConfigService,
    agentToolBindingService,
    feedbackLearningService,
    mrSyncService,
    observabilityService,
    staticToolAvailabilityService,
    projectConfigService,
    reviewQueueService,
    all,
    get,
    runWorkerOnce,
    repoConfig,
    riskScore,
    verifyGitHubSignature,
    verifyCodeHubSignature,
    normalizeCodeHubWebhookPayload,
    codehubRepoMatches,
    bearerToken,
    currentUserId,
    ensureProjectRole,
    ensureProjectWrite,
    ensureRoot,
    auditLog,
    syncProject,
    publishFindings,
    formatPublishBody
  };

  return [
    ...createHealthRoutes(ctx),
    ...createAuthRoutes(ctx),
    ...createProjectRoutes(ctx),
    ...createRuleRoutes(ctx),
    ...createAgentRoutes(ctx),
    ...createRepositoryRoutes(ctx),
    ...createSystemRoutes(ctx),
    ...createObservabilityRoutes(ctx),
    ...createWebhookRoutes(ctx),
    ...createReviewRoutes(ctx),
    ...createFullReviewRoutes(ctx),
    ...createQualityRoutes(ctx),
    ...createVcsProxyRoutes(ctx)
  ];
}
