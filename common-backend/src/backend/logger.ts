import { appendFileSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import type { AppConfig } from "./types.js";

type LogLevel = "info" | "warn" | "error";

function loggingConfig(config: AppConfig) {
  return {
    enabled: config.logging?.enabled ?? true,
    dir: config.logging?.dir ?? "logs",
    apiFile: config.logging?.api_file ?? "jolt-api.log",
    workerFile: config.logging?.worker_file ?? "jolt-worker.log",
    reviewRunDir: config.logging?.review_run_dir ?? "review-runs"
  };
}

function resolveLogDir(config: AppConfig): string {
  const logging = loggingConfig(config);
  const dir = path.isAbsolute(logging.dir) ? logging.dir : path.resolve(process.cwd(), logging.dir);
  mkdirSync(dir, { recursive: true });
  return dir;
}

function resolveLogFile(config: AppConfig): string {
  const logging = loggingConfig(config);
  const dir = resolveLogDir(config);
  return path.join(dir, logging.apiFile);
}

export function clearLogFiles(config: AppConfig) {
  const logging = loggingConfig(config);
  if (!logging.enabled) return;
  const dir = resolveLogDir(config);
  for (const target of [
    path.join(dir, logging.apiFile),
    path.join(dir, logging.workerFile),
    path.join(dir, logging.reviewRunDir)
  ]) {
    rmSync(target, { recursive: true, force: true });
  }
}

function beijingIsoString() {
  return new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString().replace("Z", "+08:00");
}

function redactField(key: string, value: unknown): unknown {
  if (value == null) return value;
  const normalized = key.toLowerCase();
  const sensitiveKeys = new Set(["token", "access_token", "refresh_token", "api_key", "apikey", "secret", "authorization", "password"]);
  if (sensitiveKeys.has(normalized) || /(^|_)(api[_-]?key|secret|authorization|password)$/.test(normalized)) return "<redacted>";
  return value;
}

function sanitize(fields: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(fields).map(([key, value]) => [key, redactField(key, value)]));
}

export class FileLogger {
  private filePath: string | null;

  constructor(private readonly config: AppConfig) {
    this.filePath = loggingConfig(config).enabled ? resolveLogFile(config) : null;
  }

  log(event: string, fields: Record<string, unknown> = {}, level: LogLevel = "info") {
    if (!this.filePath) return;
    const line = JSON.stringify({
      ts: beijingIsoString(),
      service: "jolt-api",
      level,
      event,
      ...sanitize(fields)
    });
    appendFileSync(this.filePath, `${line}\n`, "utf8");
  }

  error(event: string, error: unknown, fields: Record<string, unknown> = {}) {
    this.log(event, {
      ...fields,
      error_name: error instanceof Error ? error.name : "Error",
      error_message: error instanceof Error ? error.message : String(error)
    }, "error");
  }
}
