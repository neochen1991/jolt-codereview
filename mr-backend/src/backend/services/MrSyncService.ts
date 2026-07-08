import type { AppConfig } from "../types.js";
import type { MergeRequestRepository } from "../repositories/MergeRequestRepository.js";
import type { RepositoryRepository, RepositoryRow } from "../repositories/RepositoryRepository.js";
import type { ReviewQueueService } from "./ReviewQueueService.js";
import { CodeHubProvider } from "../vcs/CodeHubProvider.js";
import { GithubProvider } from "../vcs/GithubProvider.js";
import type { MergeRequestRemoteStatus, NormalizedMergeRequest, VcsProvider } from "../vcs/VcsProvider.js";

function riskScore(input: { additions?: number; deletions?: number; changedFiles?: number; changed_files?: number }): number {
  const churn = (input.additions ?? 0) + (input.deletions ?? 0);
  return Math.min(100, Math.round((input.changedFiles ?? input.changed_files ?? 0) * 8 + churn / 35));
}

function terminalReviewStatus(status: MergeRequestRemoteStatus): "merged" | "closed" | null {
  if (status.state === "merged") return "merged";
  if (status.state === "closed") return "closed";
  return null;
}

function positiveInt(value: unknown, fallback: number, min = 1, max = 20) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return fallback;
  return Math.max(min, Math.min(max, Math.floor(number)));
}

async function mapLimit<T, R>(items: T[], concurrency: number, handler: (item: T, index: number) => Promise<R>): Promise<R[]> {
  const results = new Array<R>(items.length);
  let nextIndex = 0;
  const workers = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (nextIndex < items.length) {
      const currentIndex = nextIndex;
      nextIndex += 1;
      results[currentIndex] = await handler(items[currentIndex], currentIndex);
    }
  });
  await Promise.all(workers);
  return results;
}

type StatusRefreshItem = {
  ok: boolean;
  merge_request_id: string;
  number?: number;
  title?: string;
  remote_status?: MergeRequestRemoteStatus;
  terminal_status?: "merged" | "closed" | null;
  blocked?: boolean;
  reason?: string;
  error?: string;
};

export class MrSyncService {
  private readonly providers: Record<string, VcsProvider>;

  constructor(
    private readonly config: AppConfig,
    private readonly repositoryRepository: RepositoryRepository,
    private readonly mergeRequestRepository: MergeRequestRepository,
    private readonly reviewQueueService: ReviewQueueService,
    private readonly runWorkerOnce: () => void,
    private readonly effectiveConfig?: (projectId: string) => Promise<AppConfig>
  ) {
    this.providers = {
      github: new GithubProvider(config),
      codehub: new CodeHubProvider(config)
    };
  }

  private async effectiveConfigForProject(projectId: string): Promise<AppConfig> {
    return this.effectiveConfig ? await this.effectiveConfig(projectId) : this.config;
  }

  private providersFor(config: AppConfig): Record<string, VcsProvider> {
    return config === this.config
      ? this.providers
      : {
          github: new GithubProvider(config),
          codehub: new CodeHubProvider(config)
        };
  }

  private syncConcurrency() {
    return positiveInt(
      process.env.MR_SYNC_CONCURRENCY ?? this.config.queue_policy?.sync_concurrency,
      4,
      1,
      12
    );
  }

  private statusRefreshConcurrency() {
    return positiveInt(
      process.env.MR_STATUS_REFRESH_CONCURRENCY ?? this.config.queue_policy?.status_refresh_concurrency,
      6,
      1,
      16
    );
  }

  async syncProject(projectId: string, requestedBy?: string | null) {
    const repos = this.repositoryRepository.listActiveByProject(projectId);
    const providers = this.providersFor(await this.effectiveConfigForProject(projectId));
    const repositoryResults = await mapLimit(repos, this.syncConcurrency(), async (repo): Promise<{
      repository_id: string;
      name: string;
      provider: string;
      external_repo_id: string;
      merge_requests: number;
      jobs_created: number;
      skipped_too_large: number;
      error?: string;
    }> => {
      const provider = providers[repo.provider];
      if (!provider) {
        return {
          repository_id: repo.id,
          name: repo.name,
          provider: repo.provider,
          external_repo_id: repo.external_repo_id,
          merge_requests: 0,
          jobs_created: 0,
          skipped_too_large: 0,
          error: `unsupported provider ${repo.provider}`
        };
      }
      try {
        const mergeRequests = await provider.listOpenMergeRequests(repo);
        let repoJobs = 0;
        for (const mergeRequest of mergeRequests) {
          const result = this.upsertAndEnqueue(repo, mergeRequest, requestedBy);
          if (result.jobCreated) {
            repoJobs += 1;
          }
        }
        return {
          repository_id: repo.id,
          name: repo.name,
          provider: repo.provider,
          external_repo_id: repo.external_repo_id,
          merge_requests: mergeRequests.length,
          jobs_created: repoJobs,
          skipped_too_large: 0
        };
      } catch (error) {
        const message = (error as Error).message;
        return {
          repository_id: repo.id,
          name: repo.name,
          provider: repo.provider,
          external_repo_id: repo.external_repo_id,
          merge_requests: 0,
          jobs_created: 0,
          skipped_too_large: 0,
          error: message
        };
      }
    });

    const jobs = repositoryResults.reduce((total, item) => total + item.jobs_created, 0);
    const merged = repositoryResults.reduce((total, item) => total + item.merge_requests, 0);
    const errors = repositoryResults.filter((item) => item.error).map((item) => `${item.name}: ${item.error}`);
    if (jobs > 0) this.runWorkerOnce();
    const skippedTooLarge = repositoryResults.reduce((total, item) => total + item.skipped_too_large, 0);
    return { repositories: repos.length, merge_requests: merged, jobs_created: jobs, skipped_too_large: skippedTooLarge, errors, repository_results: repositoryResults };
  }

  upsertAndEnqueue(repository: RepositoryRow, mergeRequest: NormalizedMergeRequest, requestedBy?: string | null) {
    const mrId = `mr_${repository.id}_${mergeRequest.externalId}`;
    const existing = this.mergeRequestRepository.findByRepositoryAndExternalId(repository.id, mergeRequest.externalId);
    const score = riskScore(mergeRequest);
    this.mergeRequestRepository.upsert({
      id: existing?.id ?? mrId,
      repositoryId: repository.id,
      externalMrId: mergeRequest.externalId,
      number: mergeRequest.number,
      title: mergeRequest.title,
      author: mergeRequest.author,
      sourceBranch: mergeRequest.sourceBranch,
      targetBranch: mergeRequest.targetBranch,
      riskScore: score,
      latestHeadSha: mergeRequest.headSha,
      htmlUrl: mergeRequest.htmlUrl,
      createdAt: mergeRequest.createdAt,
      metadata: mergeRequest.metadata
    });
    if (existing && existing.latest_head_sha !== mergeRequest.headSha) {
      this.reviewQueueService.supersedeQueued(existing.id);
    }
    if (existing?.review_status === "too_large") {
      this.mergeRequestRepository.updateReviewStatus(existing.id, "queued");
    }
    const jobResult = this.reviewQueueService.enqueueIdempotent({
      mergeRequestId: existing?.id ?? mrId,
      headSha: mergeRequest.headSha,
      priority: score,
      effortLevel: "standard",
      requestedBy: requestedBy ?? null
    });
    return {
      mergeRequestId: existing?.id ?? mrId,
      riskScore: score,
      jobCreated: jobResult.created,
      skippedTooLarge: false
    };
  }

  async refreshMergeRequestStatusById(mergeRequestId: string) {
    const mr = this.mergeRequestRepository.findById(mergeRequestId);
    if (!mr) return { ok: false, reason: "merge_request_not_found" };
    const repository = this.repositoryRepository.findById(mr.repository_id);
    if (!repository) return { ok: false, reason: "repository_not_found" };
    const providers = this.providersFor(await this.effectiveConfigForProject(repository.project_id));
    const provider = providers[repository.provider];
    if (!provider) return { ok: false, reason: `unsupported provider ${repository.provider}` };
    const remoteStatus = await provider.fetchMergeRequestStatus({
      repository,
      number: mr.number,
      externalId: mr.external_mr_id,
      headSha: mr.latest_head_sha
    });
    const terminalStatus = terminalReviewStatus(remoteStatus);
    if (terminalStatus) {
      this.reviewQueueService.stopByMergeRequest(mergeRequestId);
      this.mergeRequestRepository.updateReviewStatus(mergeRequestId, terminalStatus);
    }
    return {
      ok: true,
      merge_request_id: mergeRequestId,
      remote_status: remoteStatus,
      terminal_status: terminalStatus,
      blocked: Boolean(terminalStatus)
    };
  }

  private async refreshMergeRequestStatusRow(row: Record<string, any>, providers: Record<string, VcsProvider>) {
    const provider = providers[String(row.provider || "")];
    if (!provider) return { ok: false, merge_request_id: String(row.id), number: Number(row.number || 0), title: String(row.title || ""), reason: `unsupported provider ${row.provider}` };
    const remoteStatus = await provider.fetchMergeRequestStatus({
      repository: row as RepositoryRow,
      number: Number(row.number),
      externalId: String(row.external_mr_id),
      headSha: String(row.latest_head_sha)
    });
    const terminalStatus = terminalReviewStatus(remoteStatus);
    if (terminalStatus) {
      this.reviewQueueService.stopByMergeRequest(String(row.id));
      this.mergeRequestRepository.updateReviewStatus(String(row.id), terminalStatus);
    }
    return {
      ok: true,
      merge_request_id: String(row.id),
      number: Number(row.number || 0),
      title: String(row.title || ""),
      remote_status: remoteStatus,
      terminal_status: terminalStatus,
      blocked: Boolean(terminalStatus)
    } satisfies StatusRefreshItem;
  }

  async refreshProjectMergeRequestStatuses(projectId: string) {
    const rows = this.mergeRequestRepository.listRemoteStatusCandidates(projectId) as Array<Record<string, any>>;
    const providers = this.providersFor(await this.effectiveConfigForProject(projectId));
    const items = await mapLimit<Record<string, any>, StatusRefreshItem>(rows, this.statusRefreshConcurrency(), async (row) => {
      try {
        return await this.refreshMergeRequestStatusRow(row, providers);
      } catch (error) {
        const message = (error as Error).message;
        return { ok: false, merge_request_id: String(row.id), number: Number(row.number || 0), title: String(row.title || ""), error: message };
      }
    });
    const refreshed = items.filter((item) => item.ok).length;
    const merged = items.filter((item) => item.terminal_status === "merged").length;
    const closed = items.filter((item) => item.terminal_status === "closed").length;
    const errors = items
      .filter((item) => !item.ok)
      .map((item) => `!${item.number || ""} ${item.title || item.merge_request_id}: ${item.error || item.reason || "refresh failed"}`);
    return { checked: rows.length, refreshed, merged, closed, errors, items };
  }
}
