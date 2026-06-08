import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import type { AppConfig } from "./types.js";

const DEFAULT_CONFIG: AppConfig = {
  llm: {
    default_provider: "dashscope-openai-compatible",
    default_base_url: "https://ark.cn-beijing.volces.com/api/coding/v3",
    default_model: "MiniMax-M2.7",
    default_api_key_env: null,
    default_api_key: null,
    request_timeout_seconds: 120,
    max_output_tokens: 8192,
    enable_stream: true
  },
  github: {
    default_token_env: "GITHUB_TOKEN",
    default_endpoint: "https://api.github.com"
  },
  codehub: {
    default_token_env: "CODEHUB_TOKEN",
    default_endpoint: ""
  },
  server: {
    host: "127.0.0.1",
    port: 8011,
    database_path: "data/jolt-codereview.sqlite"
  },
  logging: {
    enabled: true,
    dir: "logs",
    api_file: "jolt-api.log",
    worker_file: "jolt-worker.log",
    review_run_dir: "review-runs"
  },
  runtime: {
    python_bin: null
  }
};

function mergeConfig(base: AppConfig, override: AppConfig): AppConfig {
  return {
    ...base,
    ...override,
    llm: { ...base.llm, ...override.llm },
    github: { ...base.github, ...override.github },
    codehub: { ...base.codehub, ...override.codehub },
    server: { ...base.server, ...override.server },
    logging: { ...base.logging, ...override.logging },
    runtime: { ...base.runtime, ...override.runtime }
  };
}

export function loadConfig(): AppConfig {
  const explicitPath = process.env.CONFIG_PATH;
  const configPath = explicitPath
    ? path.resolve(explicitPath)
    : path.resolve(process.cwd(), "config.json");

  if (!existsSync(configPath)) {
    return DEFAULT_CONFIG;
  }

  const parsed = JSON.parse(readFileSync(configPath, "utf8")) as AppConfig;
  return mergeConfig(DEFAULT_CONFIG, parsed);
}

export function resolveGithubToken(config: AppConfig, tokenEnv?: string | null, token?: string | null): string | null {
  if (tokenEnv && process.env[tokenEnv]) return process.env[tokenEnv] ?? null;
  if (token) return token;
  const defaultEnv = config.github?.default_token_env;
  if (defaultEnv && process.env[defaultEnv]) return process.env[defaultEnv] ?? null;
  return null;
}

export function redacted(value: string | null | undefined): string {
  if (!value) return "<empty>";
  const last4 = value.slice(-4);
  return `****${last4}`;
}
