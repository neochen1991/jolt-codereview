import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import type { AppConfig } from "./types.js";

const DEFAULT_CONFIG: AppConfig = {
  llm: {
    default_provider: "dashscope-openai-compatible",
    default_base_url: "https://ark.cn-beijing.volces.com/api/coding/v3",
    default_model: "MiniMax-M2.7",
    default_api_key_env: "MINIMAX_API_KEY",
    request_timeout_seconds: 120,
    max_output_tokens: 8192,
    enable_stream: true
  },
  server: {
    host: "127.0.0.1",
    port: 9021,
    common_port: 9022,
    mr_port: 9021,
    database_driver: "postgres",
    postgres_url: "",
    postgres_user: "",
    postgres_password: "",
    postgres_query_timeout_seconds: 120
  },
  logging: {
    enabled: true,
    dir: "logs",
    api_file: "jolt-common-api.log"
  }
};

function mergeConfig(base: AppConfig, override: AppConfig): AppConfig {
  return {
    ...base,
    ...override,
    llm: { ...base.llm, ...override.llm },
    server: { ...base.server, ...override.server },
    logging: { ...base.logging, ...override.logging }
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

export function redacted(value: string | null | undefined): string {
  if (!value) return "<empty>";
  const last4 = value.slice(-4);
  return `****${last4}`;
}
