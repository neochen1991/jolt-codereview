import type { AppConfig, RepositoryConfig, VcsProviderName } from "./types.js";

export interface ParsedGitRepository {
  gitUrl: string;
  host: string;
  path: string;
  parts: string[];
  owner: string;
  repo: string;
  name: string;
}

function stripGitSuffix(value: string) {
  return value.replace(/\.git$/i, "");
}

function normalizePath(pathname: string) {
  return stripGitSuffix(pathname.replace(/^\/+|\/+$/g, ""));
}

export function parseGitRepositoryUrl(input: string): ParsedGitRepository {
  const value = input.trim();
  if (!value) throw new Error("git_url is required");

  let host = "";
  let path = "";

  const scpLike = value.match(/^(?:[^@/\s]+@)?([^:/\s]+):(.+)$/);
  if (scpLike && !value.includes("://")) {
    host = scpLike[1];
    path = normalizePath(scpLike[2]);
  } else if (value.includes("://")) {
    const url = new URL(value);
    host = url.hostname;
    path = normalizePath(url.pathname);
  } else {
    path = normalizePath(value);
  }

  const parts = path.split("/").filter(Boolean);
  if (parts.length < 2) {
    throw new Error("git_url must point to a repository, for example https://github.com/org/repo.git");
  }

  const owner = parts[parts.length - 2];
  const repo = parts[parts.length - 1];
  const gitUrl = host ? `https://${host}/${path}.git` : `${path}.git`;

  return {
    gitUrl,
    host,
    path,
    parts,
    owner,
    repo,
    name: repo
  };
}

export function inferProviderFromGitUrl(parsed: ParsedGitRepository): VcsProviderName | null {
  if (parsed.host.toLowerCase() === "github.com") return "github";
  return null;
}

export function repositoryConfigFromGitUrl(
  config: AppConfig,
  provider: VcsProviderName,
  parsed: ParsedGitRepository,
  providerInput: Record<string, unknown>
): RepositoryConfig {
  if (provider === "github") {
    return {
      endpoint: config.github?.default_endpoint ?? "https://api.github.com",
      owner: parsed.owner,
      repo: parsed.repo,
      git_url: parsed.gitUrl,
      git_host: parsed.host,
      full_name: `${parsed.owner}/${parsed.repo}`,
      token_env: config.github?.default_token_env ?? "GITHUB_TOKEN",
      ...providerInput
    };
  }

  return {
    endpoint: config.codehub?.default_endpoint ?? "",
    project_key: parsed.parts[0],
    repo: parsed.repo,
    repo_id: parsed.path,
    git_url: parsed.gitUrl,
    git_host: parsed.host,
    full_name: parsed.path,
    token_env: config.codehub?.default_token_env ?? "CODEHUB_TOKEN",
    ...providerInput
  };
}
