import type { Db } from "../db.js";
import type { AppConfig, FindingRow, MergeRequestRow, RepositoryConfig } from "../types.js";
import type { AgentRepository } from "../repositories/AgentRepository.js";
import type { AuditRepository } from "../repositories/AuditRepository.js";
import type { MergeRequestRepository } from "../repositories/MergeRequestRepository.js";
import type { ProjectRepository } from "../repositories/ProjectRepository.js";
import type { RepositoryRepository } from "../repositories/RepositoryRepository.js";
import type { ReviewJobRepository } from "../repositories/ReviewJobRepository.js";
import type { RuleDocumentRepository } from "../repositories/RuleDocumentRepository.js";
import type { AgentConfigService } from "../services/AgentConfigService.js";
import type { AgentToolBindingService } from "../services/AgentToolBindingService.js";
import type { FeedbackLearningService } from "../services/FeedbackLearningService.js";
import type { MrSyncService } from "../services/MrSyncService.js";
import type { ObservabilityService } from "../services/ObservabilityService.js";
import type { ProjectConfigService } from "../services/ProjectConfigService.js";
import type { ReviewQueueService } from "../services/ReviewQueueService.js";
import type { StaticToolAvailabilityService } from "../services/StaticToolAvailabilityService.js";

export interface MrSyncRepositoryResult {
  repository_id: string;
  name: string;
  provider: string;
  external_repo_id: string;
  merge_requests: number;
  jobs_created: number;
  error?: string;
}

export interface MrSyncProjectResult {
  repositories: number;
  merge_requests: number;
  jobs_created: number;
  errors: string[];
  repository_results: MrSyncRepositoryResult[];
}

export interface BackendRouteContext {
  config: AppConfig;
  db: Db;
  projectRepository: ProjectRepository;
  repositoryRepository: RepositoryRepository;
  mergeRequestRepository: MergeRequestRepository;
  reviewJobRepository: ReviewJobRepository;
  agentRepository: AgentRepository;
  ruleDocumentRepository: RuleDocumentRepository;
  auditRepository: AuditRepository;
  agentConfigService: AgentConfigService;
  agentToolBindingService: AgentToolBindingService;
  feedbackLearningService: FeedbackLearningService;
  mrSyncService: MrSyncService;
  observabilityService: ObservabilityService;
  staticToolAvailabilityService: StaticToolAvailabilityService;
  projectConfigService: ProjectConfigService;
  reviewQueueService: ReviewQueueService;
  all<T>(sql: string, params?: any[]): T[];
  get<T>(sql: string, params?: any[]): T | undefined;
  runWorkerOnce(): void;
  repoConfig(row: { provider_config_json: string }): RepositoryConfig;
  riskScore(pull: { additions?: number; deletions?: number; changed_files?: number }): number;
  verifyGitHubSignature(secret: string | undefined, rawBody: string, signature: string | null): boolean;
  verifyCodeHubSignature(secret: string | undefined, rawBody: string, signature: string | null): boolean;
  normalizeCodeHubWebhookPayload(payload: Record<string, any>): {
    action: string;
    repoFullName: string;
    externalId: string;
    number: number;
    title: string;
    author: string;
    sourceBranch: string;
    targetBranch: string;
    headSha: string;
    htmlUrl: string;
    state: string;
    additions: number;
    deletions: number;
    changedFiles: number;
  };
  codehubRepoMatches(row: { external_repo_id: string; provider_config_json: string }, repoFullName: string): boolean;
  bearerToken(req: { headers: Record<string, any> }): string | null;
  currentUserId(req: { headers: Record<string, any> }): string;
  ensureProjectRole(projectId: string, userId: string, minRole: string): { statusCode: number; error: string; message: string } | null;
  ensureProjectWrite(projectId: string, userId?: string): { statusCode: number; error: string; message: string } | null;
  ensureRoot(userId: string): { statusCode: number; error: string; message: string } | null;
  auditLog(input: {
    userId?: string;
    projectId?: string;
    action: string;
    resourceType: string;
    resourceId?: string;
    summary?: string;
    metadata?: Record<string, unknown>;
  }): void;
  syncProject(projectId: string, requestedBy?: string | null): Promise<MrSyncProjectResult>;
  publishFindings(
    mrId: string,
    findingIds: string[],
    dryRun: boolean,
    userId?: string
  ): Promise<
    | ReturnType<typeof import("../http.js").notFound>
    | ReturnType<typeof import("../http.js").badRequest>
    | { comment_ref: string; dry_run: boolean; body: string; published_count: number }
  >;
    formatPublishBody(mr: MergeRequestRow, findings: FindingRow[], provider?: string): string;
}
