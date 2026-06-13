import type { RepositoryRow } from "../repositories/RepositoryRepository.js";

export interface NormalizedMergeRequest {
  externalId: string;
  number: number;
  title: string;
  author: string;
  sourceBranch: string;
  targetBranch: string;
  headSha: string;
  htmlUrl: string;
  additions: number;
  deletions: number;
  changedFiles: number;
  metadata: Record<string, unknown>;
}

export interface VcsCapabilities {
  inline_comment: boolean;
  status_check: boolean;
  thread_reply: boolean;
  draft_review: boolean;
  diff: boolean;
  files: boolean;
}

export interface MrRef {
  repository: RepositoryRow;
  number: number;
  externalId?: string;
  headSha?: string;
}

export interface DiffPayload {
  provider: string;
  diff: string;
  files?: unknown[];
}

export interface InlineComment {
  body: string;
  filePath?: string;
  line?: number;
  side?: "LEFT" | "RIGHT";
}

export interface ReviewStatus {
  state: "pending" | "running" | "success" | "failed" | "warning";
  description: string;
  targetUrl?: string;
  context?: string;
}

export interface MergeRequestRemoteStatus {
  state: "open" | "closed" | "merged" | "unknown";
  rawState?: string;
  merged?: boolean;
}

export interface VcsProvider {
  provider: string;
  listOpenMergeRequests(repository: RepositoryRow): Promise<NormalizedMergeRequest[]>;
  fetchMergeRequestStatus(mr: MrRef): Promise<MergeRequestRemoteStatus>;
  fetchDiff(mr: MrRef): Promise<DiffPayload>;
  fetchFiles(mr: MrRef): Promise<unknown[]>;
  fetchFile(mr: MrRef, path: string, sha?: string): Promise<string>;
  postComment(mr: MrRef, comment: InlineComment): Promise<{ id: string; html_url?: string }>;
  postSummary(mr: MrRef, body: string): Promise<{ id: string; html_url?: string }>;
  updateStatus(mr: MrRef, status: ReviewStatus): Promise<void>;
  capabilities(): VcsCapabilities;
}
