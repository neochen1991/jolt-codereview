import type { AppConfig } from "../types.js";
import type { MergeRequestRepository } from "../repositories/MergeRequestRepository.js";
import type { RepositoryRepository, RepositoryRow } from "../repositories/RepositoryRepository.js";
import type { ReviewQueueService } from "./ReviewQueueService.js";
import { CodeHubProvider } from "../vcs/CodeHubProvider.js";
import { GithubProvider } from "../vcs/GithubProvider.js";
import type { NormalizedMergeRequest, VcsProvider } from "../vcs/VcsProvider.js";

function riskScore(input: { additions?: number; deletions?: number; changedFiles?: number; changed_files?: number }): number {
  const churn = (input.additions ?? 0) + (input.deletions ?? 0);
  return Math.min(100, Math.round((input.changedFiles ?? input.changed_files ?? 0) * 8 + churn / 35));
}

export class MrSyncService {
  private readonly providers: Record<string, VcsProvider>;

  constructor(
    config: AppConfig,
    private readonly repositoryRepository: RepositoryRepository,
    private readonly mergeRequestRepository: MergeRequestRepository,
    private readonly reviewQueueService: ReviewQueueService,
    private readonly runWorkerOnce: () => void
  ) {
    this.providers = {
      github: new GithubProvider(config),
      codehub: new CodeHubProvider(config)
    };
  }

  async syncProject(projectId: string) {
    const repos = this.repositoryRepository.listActiveByProject(projectId);
    let merged = 0;
    let jobs = 0;
    const errors: string[] = [];
    const repositoryResults: Array<{
      repository_id: string;
      name: string;
      provider: string;
      external_repo_id: string;
      merge_requests: number;
      jobs_created: number;
      error?: string;
    }> = [];

    for (const repo of repos) {
      const provider = this.providers[repo.provider];
      if (!provider) {
        const error = `unsupported provider ${repo.provider}`;
        errors.push(`${repo.name}: ${error}`);
        repositoryResults.push({
          repository_id: repo.id,
          name: repo.name,
          provider: repo.provider,
          external_repo_id: repo.external_repo_id,
          merge_requests: 0,
          jobs_created: 0,
          error
        });
        continue;
      }
      try {
        const mergeRequests = await provider.listOpenMergeRequests(repo);
        let repoJobs = 0;
        for (const mergeRequest of mergeRequests) {
          const result = this.upsertAndEnqueue(repo, mergeRequest);
          if (result.jobCreated) {
            jobs += 1;
            repoJobs += 1;
          }
          merged += 1;
        }
        repositoryResults.push({
          repository_id: repo.id,
          name: repo.name,
          provider: repo.provider,
          external_repo_id: repo.external_repo_id,
          merge_requests: mergeRequests.length,
          jobs_created: repoJobs
        });
      } catch (error) {
        const message = (error as Error).message;
        errors.push(`${repo.name}: ${message}`);
        repositoryResults.push({
          repository_id: repo.id,
          name: repo.name,
          provider: repo.provider,
          external_repo_id: repo.external_repo_id,
          merge_requests: 0,
          jobs_created: 0,
          error: message
        });
      }
    }

    if (jobs > 0) this.runWorkerOnce();
    return { repositories: repos.length, merge_requests: merged, jobs_created: jobs, errors, repository_results: repositoryResults };
  }

  upsertAndEnqueue(repository: RepositoryRow, mergeRequest: NormalizedMergeRequest) {
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
      metadata: mergeRequest.metadata
    });
    if (existing && existing.latest_head_sha !== mergeRequest.headSha) {
      this.reviewQueueService.supersedeQueued(existing.id);
    }
    const jobResult = this.reviewQueueService.enqueueIdempotent({
      mergeRequestId: existing?.id ?? mrId,
      headSha: mergeRequest.headSha,
      priority: score,
      effortLevel: "standard"
    });
    return {
      mergeRequestId: existing?.id ?? mrId,
      riskScore: score,
      jobCreated: jobResult.created
    };
  }
}
