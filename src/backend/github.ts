import type { AppConfig, RepositoryConfig } from "./types.js";
import { resolveGithubToken } from "./config.js";
import { parseGitRepositoryUrl } from "./repositoryIdentity.js";

export interface GitHubPull {
  id: number;
  number: number;
  title: string;
  html_url: string;
  state: string;
  draft: boolean;
  user: { login: string };
  head: { ref: string; sha: string };
  base: { ref: string; sha: string };
  updated_at: string;
  additions?: number;
  deletions?: number;
  changed_files?: number;
}

export interface GitHubFile {
  filename: string;
  status: string;
  additions: number;
  deletions: number;
  changes: number;
  patch?: string;
}

function headers(token: string | null): Record<string, string> {
  return {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "jolt-codereview-local",
    ...(token ? { "Authorization": `Bearer ${token}` } : {})
  };
}

function endpoint(config: AppConfig, repoConfig: RepositoryConfig): string {
  return (repoConfig.endpoint || config.github?.default_endpoint || "https://api.github.com").replace(/\/$/, "");
}

function ownerRepo(repoConfig: RepositoryConfig): { owner: string; repo: string } {
  if (repoConfig.owner && repoConfig.repo) {
    return { owner: repoConfig.owner, repo: repoConfig.repo };
  }
  if (repoConfig.git_url) {
    const parsed = parseGitRepositoryUrl(repoConfig.git_url);
    return { owner: parsed.owner, repo: parsed.repo };
  }
  throw new Error("GitHub repository config requires owner and repo");
}

export async function listOpenPulls(config: AppConfig, repoConfig: RepositoryConfig): Promise<GitHubPull[]> {
  const { owner, repo } = ownerRepo(repoConfig);
  const token = resolveGithubToken(config, repoConfig.token_env, repoConfig.token);
  const url = `${endpoint(config, repoConfig)}/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/pulls?state=open&per_page=50`;
  const response = await fetch(url, { headers: headers(token) });
  if (!response.ok) {
    throw new Error(`GitHub list pulls failed: ${response.status} ${await response.text()}`);
  }
  return (await response.json()) as GitHubPull[];
}

export async function listPullFiles(config: AppConfig, repoConfig: RepositoryConfig, number: number): Promise<GitHubFile[]> {
  const { owner, repo } = ownerRepo(repoConfig);
  const token = resolveGithubToken(config, repoConfig.token_env, repoConfig.token);
  const url = `${endpoint(config, repoConfig)}/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/pulls/${number}/files?per_page=100`;
  const response = await fetch(url, { headers: headers(token) });
  if (!response.ok) {
    throw new Error(`GitHub list pull files failed: ${response.status} ${await response.text()}`);
  }
  return (await response.json()) as GitHubFile[];
}

export async function fetchPullDiff(config: AppConfig, repoConfig: RepositoryConfig, number: number): Promise<string> {
  const { owner, repo } = ownerRepo(repoConfig);
  const token = resolveGithubToken(config, repoConfig.token_env, repoConfig.token);
  const url = `${endpoint(config, repoConfig)}/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/pulls/${number}`;
  const response = await fetch(url, { headers: { ...headers(token), Accept: "application/vnd.github.v3.diff" } });
  if (!response.ok) {
    throw new Error(`GitHub fetch pull diff failed: ${response.status} ${await response.text()}`);
  }
  return await response.text();
}

export async function fetchRepoFile(config: AppConfig, repoConfig: RepositoryConfig, path: string, sha?: string): Promise<string> {
  const { owner, repo } = ownerRepo(repoConfig);
  const token = resolveGithubToken(config, repoConfig.token_env, repoConfig.token);
  const query = sha ? `?ref=${encodeURIComponent(sha)}` : "";
  const encodedPath = path
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
  const url = `${endpoint(config, repoConfig)}/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/contents/${encodedPath}${query}`;
  const response = await fetch(url, { headers: headers(token) });
  if (!response.ok) {
    throw new Error(`GitHub fetch file failed: ${response.status} ${await response.text()}`);
  }
  const json = await response.json() as { content?: string; encoding?: string };
  if (json.encoding === "base64" && json.content) return Buffer.from(json.content, "base64").toString("utf-8");
  return String(json.content ?? "");
}

export async function postIssueComment(
  config: AppConfig,
  repoConfig: RepositoryConfig,
  number: number,
  body: string
): Promise<{ id: string; html_url?: string }> {
  const { owner, repo } = ownerRepo(repoConfig);
  const token = resolveGithubToken(config, repoConfig.token_env, repoConfig.token);
  if (!token) throw new Error("GitHub token is required to publish comments");
  const url = `${endpoint(config, repoConfig)}/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/issues/${number}/comments`;
  const response = await fetch(url, {
    method: "POST",
    headers: { ...headers(token), "Content-Type": "application/json" },
    body: JSON.stringify({ body })
  });
  if (!response.ok) {
    throw new Error(`GitHub publish comment failed: ${response.status} ${await response.text()}`);
  }
  const json = await response.json() as { id: number; html_url?: string };
  return { id: String(json.id), html_url: json.html_url };
}

export async function updateCommitStatus(
  config: AppConfig,
  repoConfig: RepositoryConfig,
  sha: string,
  status: { state: "pending" | "success" | "failure" | "error"; description: string; target_url?: string; context?: string }
): Promise<void> {
  const { owner, repo } = ownerRepo(repoConfig);
  const token = resolveGithubToken(config, repoConfig.token_env, repoConfig.token);
  if (!token) throw new Error("GitHub token is required to update status");
  const url = `${endpoint(config, repoConfig)}/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/statuses/${encodeURIComponent(sha)}`;
  const response = await fetch(url, {
    method: "POST",
    headers: { ...headers(token), "Content-Type": "application/json" },
    body: JSON.stringify(status)
  });
  if (!response.ok) {
    throw new Error(`GitHub update status failed: ${response.status} ${await response.text()}`);
  }
}

export function normalizeRepoConfig(value: unknown): RepositoryConfig {
  if (!value || typeof value !== "object") return {};
  return value as RepositoryConfig;
}
