import type { AppConfig, RepositoryConfig } from "../types.js";
import { fetchCodeHubDiff, fetchCodeHubFile, fetchCodeHubFiles, fetchCodeHubMr, listOpenCodeHubMrs, postCodeHubSummaryComment, updateCodeHubStatus } from "../codehub.js";
import { normalizeRepoConfig } from "../github.js";
import type { RepositoryRow } from "../repositories/RepositoryRepository.js";
import type { DiffPayload, InlineComment, MergeRequestRemoteStatus, MrRef, NormalizedMergeRequest, ReviewStatus, VcsCapabilities, VcsProvider } from "./VcsProvider.js";

export class CodeHubProvider implements VcsProvider {
  provider = "codehub";

  constructor(private readonly config: AppConfig) {}

  async listOpenMergeRequests(repository: RepositoryRow): Promise<NormalizedMergeRequest[]> {
    const repoConfig = normalizeRepoConfig(JSON.parse(repository.provider_config_json || "{}")) as RepositoryConfig;
    const mrs = await listOpenCodeHubMrs(this.config, repoConfig);
    return mrs.map((mr) => {
      const author = typeof mr.author === "string"
        ? mr.author
        : String(mr.author?.username ?? mr.author?.name ?? mr.author?.login ?? "");
      return {
        externalId: String(mr.id ?? mr.iid ?? mr.number),
        number: Number(mr.number ?? mr.iid ?? mr.id),
        title: String(mr.title ?? ""),
        author,
        sourceBranch: String(mr.source_branch ?? ""),
        targetBranch: String(mr.target_branch ?? ""),
        headSha: String(mr.head_sha ?? mr.sha ?? ""),
        htmlUrl: String(mr.html_url ?? mr.web_url ?? ""),
        additions: Number(mr.additions ?? 0),
        deletions: Number(mr.deletions ?? 0),
        changedFiles: Number(mr.changed_files ?? 0),
        metadata: {
          provider: "codehub",
          additions: mr.additions ?? 0,
          deletions: mr.deletions ?? 0,
          changed_files: mr.changed_files ?? 0
        }
      };
    });
  }

  async fetchDiff(mr: MrRef): Promise<DiffPayload> {
    const repoConfig = normalizeRepoConfig(JSON.parse(mr.repository.provider_config_json || "{}")) as RepositoryConfig;
    return { provider: this.provider, diff: await fetchCodeHubDiff(this.config, repoConfig, mr.number) };
  }

  async fetchMergeRequestStatus(mr: MrRef): Promise<MergeRequestRemoteStatus> {
    const repoConfig = normalizeRepoConfig(JSON.parse(mr.repository.provider_config_json || "{}")) as RepositoryConfig;
    const mergeRequest = await fetchCodeHubMr(this.config, repoConfig, mr.number);
    const rawState = String(mergeRequest.state ?? "").toLowerCase();
    const state = rawState.includes("merged") || rawState === "merge"
      ? "merged"
      : rawState.includes("closed") || rawState === "close"
        ? "closed"
        : rawState.includes("open") || rawState === "opened"
          ? "open"
          : "unknown";
    return { state, rawState, merged: state === "merged" };
  }

  async fetchFiles(mr: MrRef): Promise<unknown[]> {
    const repoConfig = normalizeRepoConfig(JSON.parse(mr.repository.provider_config_json || "{}")) as RepositoryConfig;
    return fetchCodeHubFiles(this.config, repoConfig, mr.number);
  }

  async fetchFile(mr: MrRef, path: string, sha?: string): Promise<string> {
    const repoConfig = normalizeRepoConfig(JSON.parse(mr.repository.provider_config_json || "{}")) as RepositoryConfig;
    return fetchCodeHubFile(this.config, repoConfig, path, sha ?? mr.headSha);
  }

  async postComment(mr: MrRef, comment: InlineComment): Promise<{ id: string; html_url?: string }> {
    return this.postSummary(mr, comment.body);
  }

  async postSummary(mr: MrRef, body: string): Promise<{ id: string; html_url?: string }> {
    const repoConfig = normalizeRepoConfig(JSON.parse(mr.repository.provider_config_json || "{}")) as RepositoryConfig;
    return postCodeHubSummaryComment(this.config, repoConfig, mr.number, body);
  }

  async updateStatus(mr: MrRef, status: ReviewStatus): Promise<void> {
    const repoConfig = normalizeRepoConfig(JSON.parse(mr.repository.provider_config_json || "{}")) as RepositoryConfig;
    await updateCodeHubStatus(this.config, repoConfig, mr.number, {
      state: status.state,
      description: status.description,
      target_url: status.targetUrl,
      context: status.context ?? "jolt-codereview",
    });
  }

  capabilities(): VcsCapabilities {
    return { inline_comment: false, status_check: true, thread_reply: true, draft_review: false, diff: true, files: true };
  }
}
