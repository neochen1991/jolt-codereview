import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

export const root = path.resolve(import.meta.dirname, "..");

export function loadConfig() {
  const configPath = process.env.CONFIG_PATH || path.join(root, "config.json");
  const defaultConfig = JSON.parse(readFileSync(path.join(root, "config.example.json"), "utf8"));
  if (!existsSync(configPath)) return defaultConfig;
  const config = JSON.parse(readFileSync(configPath, "utf8"));
  return deepMerge(defaultConfig, config);
}

function deepMerge(base, override) {
  const result = { ...base };
  for (const [key, value] of Object.entries(override || {})) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      result[key] = deepMerge(result[key] || {}, value);
    } else {
      result[key] = value;
    }
  }
  return result;
}

export function resolveLlmApiKey(config) {
  const envName = config.llm?.default_api_key_env;
  if (envName && process.env[envName]) return process.env[envName];
  return config.llm?.default_api_key || null;
}

export function chatCompletionsUrl(baseUrl) {
  const cleaned = String(baseUrl || "").replace(/\/$/, "");
  if (cleaned.endsWith("/chat/completions")) return cleaned;
  return `${cleaned}/chat/completions`;
}

export function redact(value) {
  if (!value) return "<empty>";
  return `****${String(value).slice(-4)}`;
}
