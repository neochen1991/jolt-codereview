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
    database_path: "data/jolt-codereview.sqlite",
    database_driver: "sqlite",
    postgres_url: "",
    postgres_user: "",
    postgres_password: "",
    postgres_query_timeout_seconds: 120
  },
  logging: {
    enabled: true,
    dir: "logs",
    api_file: "jolt-api.log",
    worker_file: "jolt-worker.log",
    review_run_dir: "review-runs"
  },
  budget_policy: {
    efforts: {
      standard: {
        max_llm_calls: 80,
        max_wall_seconds: 1800,
        max_output_tokens: 16000,
        max_findings: 80
      },
      deep: {
        max_llm_calls: 120,
        max_wall_seconds: 2400,
        max_output_tokens: 24000,
        max_findings: 120
      }
    }
  },
  token_usage: {
    enabled: false,
    endpoint: "",
    method: "POST",
    timeout_seconds: 10,
    auth_header: "Authorization",
    auth_token_env: null,
    auth_token: null,
    employee_no_env: "JOLT_REPORTER_EMPLOYEE_NO",
    default_employee_no: "system",
    service_name: "jolt-codereview"
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
    budget_policy: { ...base.budget_policy, ...override.budget_policy },
    token_usage: { ...base.token_usage, ...override.token_usage },
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
  if (config.github?.default_token) return config.github.default_token;
  const defaultEnv = config.github?.default_token_env;
  if (defaultEnv && process.env[defaultEnv]) return process.env[defaultEnv] ?? null;
  return null;
}

export function redacted(value: string | null | undefined): string {
  if (!value) return "<empty>";
  const last4 = value.slice(-4);
  return `****${last4}`;
}
