import type { AppConfig, RepositoryConfig } from "../types.js";
import { fetchPullDiff, fetchRepoFile, listOpenPulls, listPullFiles, normalizeRepoConfig, postIssueComment, updateCommitStatus } from "../github.js";
import type { RepositoryRow } from "../repositories/RepositoryRepository.js";
import type { DiffPayload, InlineComment, MrRef, NormalizedMergeRequest, ReviewStatus, VcsCapabilities, VcsProvider } from "./VcsProvider.js";

export class GithubProvider implements VcsProvider {
  provider = "github";

  constructor(private readonly config: AppConfig) {}

  async listOpenMergeRequests(repository: RepositoryRow): Promise<NormalizedMergeRequest[]> {
    const repoConfig = normalizeRepoConfig(JSON.parse(repository.provider_config_json || "{}")) as RepositoryConfig;
    const pulls = await listOpenPulls(this.config, repoConfig);
    return pulls.map((pull) => ({
      externalId: String(pull.id),
      number: Number(pull.number),
      title: String(pull.title ?? ""),
      author: String(pull.user?.login ?? ""),
      sourceBranch: String(pull.head?.ref ?? ""),
      targetBranch: String(pull.base?.ref ?? ""),
      headSha: String(pull.head?.sha ?? ""),
      htmlUrl: String(pull.html_url ?? ""),
      additions: Number(pull.additions ?? 0),
      deletions: Number(pull.deletions ?? 0),
      changedFiles: Number(pull.changed_files ?? 0),
      metadata: {
        provider: "github",
        draft: pull.draft,
        additions: pull.additions ?? 0,
        deletions: pull.deletions ?? 0,
        changed_files: pull.changed_files ?? 0,
        base_sha: pull.base?.sha ?? ""
      }
    }));
  }

  async fetchDiff(mr: MrRef): Promise<DiffPayload> {
    const repoConfig = normalizeRepoConfig(JSON.parse(mr.repository.provider_config_json || "{}")) as RepositoryConfig;
    return { provider: this.provider, diff: await fetchPullDiff(this.config, repoConfig, mr.number) };
  }

  async fetchFiles(mr: MrRef): Promise<unknown[]> {
    const repoConfig = normalizeRepoConfig(JSON.parse(mr.repository.provider_config_json || "{}")) as RepositoryConfig;
    return listPullFiles(this.config, repoConfig, mr.number);
  }

  async fetchFile(mr: MrRef, path: string, sha?: string): Promise<string> {
    const repoConfig = normalizeRepoConfig(JSON.parse(mr.repository.provider_config_json || "{}")) as RepositoryConfig;
    return fetchRepoFile(this.config, repoConfig, path, sha ?? mr.headSha);
  }

  async postComment(mr: MrRef, comment: InlineComment): Promise<{ id: string; html_url?: string }> {
    return this.postSummary(mr, comment.body);
  }

  async postSummary(mr: MrRef, body: string): Promise<{ id: string; html_url?: string }> {
    const repoConfig = normalizeRepoConfig(JSON.parse(mr.repository.provider_config_json || "{}")) as RepositoryConfig;
    return postIssueComment(this.config, repoConfig, mr.number, body);
  }

  async updateStatus(mr: MrRef, status: ReviewStatus): Promise<void> {
    const repoConfig = normalizeRepoConfig(JSON.parse(mr.repository.provider_config_json || "{}")) as RepositoryConfig;
    const mapped = status.state === "failed"
      ? "failure"
      : status.state === "warning"
        ? "error"
        : status.state === "running"
          ? "pending"
          : status.state;
    await updateCommitStatus(this.config, repoConfig, String(mr.headSha || ""), {
      state: mapped,
      description: status.description,
      target_url: status.targetUrl,
      context: status.context ?? "jolt-codereview",
    });
  }

  capabilities(): VcsCapabilities {
    return { inline_comment: false, status_check: true, thread_reply: true, draft_review: false, diff: true, files: true };
  }
}
