import type { AppConfig, RepositoryConfig } from "./types.js";

export interface CodeHubMergeRequest {
  id: string | number;
  iid?: string | number;
  number?: string | number;
  title: string;
  web_url?: string;
  html_url?: string;
  state?: string;
  author?: { username?: string; name?: string; login?: string } | string;
  source_branch?: string;
  target_branch?: string;
  head_sha?: string;
  sha?: string;
  updated_at?: string;
  additions?: number;
  deletions?: number;
  changed_files?: number;
}

function endpoint(config: AppConfig, repoConfig: RepositoryConfig): string {
  const base = repoConfig.endpoint || config.codehub?.default_endpoint;
  if (!base) throw new Error("CodeHub repository config requires endpoint");
  return base.replace(/\/$/, "");
}

function token(config: AppConfig, repoConfig: RepositoryConfig): string | null {
  const envName = repoConfig.token_env || config.codehub?.default_token_env || "CODEHUB_TOKEN";
  if (envName && process.env[envName]) return process.env[envName] ?? null;
  return repoConfig.token ?? null;
}

function headers(config: AppConfig, repoConfig: RepositoryConfig): Record<string, string> {
  const value = token(config, repoConfig);
  return {
    "Accept": "application/json",
    "User-Agent": "jolt-codereview-local",
    ...(value ? { "Authorization": `Bearer ${value}` } : {})
  };
}

function template(value: string, repoConfig: RepositoryConfig): string {
  const replacements: Record<string, string> = {
    project_key: repoConfig.project_key ?? "",
    repo: repoConfig.repo ?? "",
    repo_id: repoConfig.repo_id ?? repoConfig.full_name ?? repoConfig.repo ?? "",
    external_repo_id: repoConfig.repo_id ?? repoConfig.full_name ?? repoConfig.repo ?? "",
    git_url: repoConfig.git_url ?? ""
  };
  return value.replace(/\{([a-zA-Z0-9_]+)\}/g, (_, key: string) => encodeURIComponent(replacements[key] ?? ""));
}

function normalizeListPayload(payload: unknown): CodeHubMergeRequest[] {
  if (Array.isArray(payload)) return payload as CodeHubMergeRequest[];
  if (payload && typeof payload === "object") {
    const object = payload as Record<string, unknown>;
    for (const key of ["items", "merge_requests", "mrs", "data", "values"]) {
      if (Array.isArray(object[key])) return object[key] as CodeHubMergeRequest[];
    }
  }
  return [];
}

export async function listOpenCodeHubMrs(config: AppConfig, repoConfig: RepositoryConfig): Promise<CodeHubMergeRequest[]> {
  const path = repoConfig.list_mrs_path ?? "/api/v1/repos/{repo_id}/merge-requests?state=open&per_page=50";
  const url = `${endpoint(config, repoConfig)}${template(path, repoConfig)}`;
  const response = await fetch(url, { headers: headers(config, repoConfig) });
  if (!response.ok) {
    throw new Error(`CodeHub list merge requests failed: ${response.status} ${await response.text()}`);
  }
  return normalizeListPayload(await response.json());
}

export async function postCodeHubSummaryComment(
  config: AppConfig,
  repoConfig: RepositoryConfig,
  mrNumber: number,
  body: string
): Promise<{ id: string; html_url?: string }> {
  const path = repoConfig.comment_path_template ?? "/api/v1/repos/{repo_id}/merge-requests/{mr_number}/comments";
  const url = `${endpoint(config, repoConfig)}${template(path.replace("{mr_number}", String(mrNumber)), repoConfig)}`;
  const response = await fetch(url, {
    method: "POST",
    headers: { ...headers(config, repoConfig), "Content-Type": "application/json" },
    body: JSON.stringify({ body, content: body, note: body })
  });
  if (!response.ok) {
    throw new Error(`CodeHub publish comment failed: ${response.status} ${await response.text()}`);
  }
  const json = await response.json() as Record<string, unknown>;
  return { id: String(json.id ?? json.comment_id ?? `codehub_${Date.now()}`), html_url: json.web_url ? String(json.web_url) : undefined };
}

export async function fetchCodeHubDiff(config: AppConfig, repoConfig: RepositoryConfig, mrNumber: number): Promise<string> {
  const path = repoConfig.diff_path_template ?? "/api/v1/repos/{repo_id}/merge-requests/{mr_number}/diff";
  const url = `${endpoint(config, repoConfig)}${template(path.replace("{mr_number}", String(mrNumber)), repoConfig)}`;
  const response = await fetch(url, { headers: headers(config, repoConfig) });
  if (!response.ok) {
    throw new Error(`CodeHub fetch diff failed: ${response.status} ${await response.text()}`);
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return JSON.stringify(await response.json());
  }
  return await response.text();
}

export async function fetchCodeHubFiles(config: AppConfig, repoConfig: RepositoryConfig, mrNumber: number): Promise<unknown[]> {
  const path = repoConfig.files_path_template ?? "/api/v1/repos/{repo_id}/merge-requests/{mr_number}/files";
  const url = `${endpoint(config, repoConfig)}${template(path.replace("{mr_number}", String(mrNumber)), repoConfig)}`;
  const response = await fetch(url, { headers: headers(config, repoConfig) });
  if (!response.ok) {
    throw new Error(`CodeHub fetch files failed: ${response.status} ${await response.text()}`);
  }
  const payload = await response.json();
  if (Array.isArray(payload)) return payload;
  if (payload && typeof payload === "object") {
    const object = payload as Record<string, unknown>;
    for (const key of ["items", "files", "changes", "data", "values"]) {
      if (Array.isArray(object[key])) return object[key] as unknown[];
    }
  }
  return [];
}

export async function fetchCodeHubFile(config: AppConfig, repoConfig: RepositoryConfig, filePath: string, sha?: string): Promise<string> {
  const path = repoConfig.file_path_template ?? "/api/v1/repos/{repo_id}/raw/{file_path}";
  const withPath = path.replace("{file_path}", encodeURIComponent(filePath));
  const withSha = sha ? `${withPath}${withPath.includes("?") ? "&" : "?"}ref=${encodeURIComponent(sha)}` : withPath;
  const url = `${endpoint(config, repoConfig)}${template(withSha, repoConfig)}`;
  const response = await fetch(url, { headers: headers(config, repoConfig) });
  if (!response.ok) {
    throw new Error(`CodeHub fetch file failed: ${response.status} ${await response.text()}`);
  }
  return await response.text();
}

export async function updateCodeHubStatus(
  config: AppConfig,
  repoConfig: RepositoryConfig,
  mrNumber: number,
  status: { state: string; description: string; target_url?: string; context?: string }
): Promise<void> {
  const path = repoConfig.status_path_template ?? "/api/v1/repos/{repo_id}/merge-requests/{mr_number}/statuses";
  const url = `${endpoint(config, repoConfig)}${template(path.replace("{mr_number}", String(mrNumber)), repoConfig)}`;
  const response = await fetch(url, {
    method: "POST",
    headers: { ...headers(config, repoConfig), "Content-Type": "application/json" },
    body: JSON.stringify(status)
  });
  if (!response.ok) {
    throw new Error(`CodeHub update status failed: ${response.status} ${await response.text()}`);
  }
}
