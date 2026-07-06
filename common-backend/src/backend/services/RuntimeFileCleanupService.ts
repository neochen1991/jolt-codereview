import { existsSync, lstatSync, readdirSync, rmSync, statSync } from "node:fs";
import path from "node:path";
import type { AppConfig } from "../types.js";

type CleanupReason = "max_age" | "max_log_size" | "max_total_size";

export interface CleanupItem {
  path: string;
  kind: "file";
  size_bytes: number;
  mtime_ms: number;
  reason: CleanupReason;
}

export interface RuntimeCleanupResult {
  dry_run: boolean;
  scanned: number;
  candidates: CleanupItem[];
  deleted: CleanupItem[];
  skipped: Array<{ path: string; reason: string }>;
  errors: Array<{ path: string; message: string }>;
}

interface CleanupOptions {
  serviceRoot?: string;
  dryRun?: boolean;
  now?: number;
}

interface RuntimeCleanupLogger {
  log(event: string, fields?: Record<string, unknown>, level?: "info" | "warn" | "error"): void;
  error?(event: string, error: unknown, fields?: Record<string, unknown>): void;
}

interface CleanupTarget {
  path: string;
  size_bytes: number;
  mtime_ms: number;
}

function cleanupPolicy(config: AppConfig) {
  const policy = config.cleanup_policy || {};
  return {
    enabled: policy.enabled ?? true,
    runOnStartup: policy.run_on_startup ?? true,
    intervalSeconds: Math.max(60, Number(policy.interval_seconds ?? 3600)),
    maxAgeDays: Math.max(0, Number(policy.max_age_days ?? 1)),
    maxTotalMb: Math.max(0, Number(policy.max_total_mb ?? 1024)),
    maxLogFileMb: Math.max(0, Number(policy.max_log_file_mb ?? 256))
  };
}

function logDir(config: AppConfig, root: string): string {
  const configured = String(config.logging?.dir || "logs");
  const resolved = path.isAbsolute(configured) ? path.resolve(configured) : path.resolve(root, configured);
  if (!isInside(root, resolved)) {
    throw new Error(`cleanup path escapes service root: ${configured}`);
  }
  return resolved;
}

function isInside(parent: string, child: string): boolean {
  const relative = path.relative(parent, child);
  return relative === "" || (!!relative && !relative.startsWith("..") && !path.isAbsolute(relative));
}

function collectLogFiles(dir: string): CleanupTarget[] {
  if (!existsSync(dir)) return [];
  const items: CleanupTarget[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith(".log")) continue;
    const filePath = path.join(dir, entry.name);
    try {
      const stat = statSync(filePath);
      items.push({ path: filePath, size_bytes: stat.size, mtime_ms: stat.mtimeMs });
    } catch {
      continue;
    }
  }
  return items;
}

function addCandidate(candidates: Map<string, CleanupItem>, target: CleanupTarget, reason: CleanupReason) {
  if (candidates.has(target.path)) return;
  candidates.set(target.path, { ...target, kind: "file", reason });
}

export function runRuntimeFileCleanup(config: AppConfig, options: CleanupOptions = {}): RuntimeCleanupResult {
  const policy = cleanupPolicy(config);
  const result: RuntimeCleanupResult = { dry_run: !!options.dryRun, scanned: 0, candidates: [], deleted: [], skipped: [], errors: [] };
  if (!policy.enabled || config.logging?.enabled === false) return result;

  const root = path.resolve(options.serviceRoot || process.cwd());
  let dir: string;
  try {
    dir = logDir(config, root);
  } catch (error) {
    result.errors.push({ path: root, message: error instanceof Error ? error.message : String(error) });
    return result;
  }

  const now = options.now ?? Date.now();
  const cutoff = now - policy.maxAgeDays * 24 * 60 * 60 * 1000;
  const maxTotalBytes = policy.maxTotalMb * 1024 * 1024;
  const maxLogFileBytes = policy.maxLogFileMb * 1024 * 1024;
  const targets = collectLogFiles(dir).filter((target) => isInside(dir, target.path));
  result.scanned = targets.length;

  const candidates = new Map<string, CleanupItem>();
  for (const target of targets) {
    if (target.mtime_ms < cutoff) {
      addCandidate(candidates, target, "max_age");
    } else if (maxLogFileBytes > 0 && target.size_bytes > maxLogFileBytes) {
      addCandidate(candidates, target, "max_log_size");
    }
  }
  if (maxTotalBytes > 0) {
    let remainingSize = targets.reduce((total, target) => total + target.size_bytes, 0);
    for (const target of [...targets].sort((left, right) => left.mtime_ms - right.mtime_ms)) {
      if (remainingSize <= maxTotalBytes) break;
      addCandidate(candidates, target, "max_total_size");
      remainingSize -= target.size_bytes;
    }
  }

  result.candidates = [...candidates.values()].sort((left, right) => left.mtime_ms - right.mtime_ms);
  if (result.dry_run) return result;

  for (const item of result.candidates) {
    if (!isInside(dir, item.path)) {
      result.skipped.push({ path: item.path, reason: "not_under_allowed_runtime_root" });
      continue;
    }
    try {
      const stat = lstatSync(item.path);
      if (stat.isSymbolicLink()) {
        result.skipped.push({ path: item.path, reason: "symbolic_link" });
        continue;
      }
      rmSync(item.path, { force: true });
      result.deleted.push(item);
    } catch (error) {
      result.errors.push({ path: item.path, message: error instanceof Error ? error.message : String(error) });
    }
  }
  return result;
}

export function startRuntimeFileCleanup(config: AppConfig, logger?: RuntimeCleanupLogger) {
  const policy = cleanupPolicy(config);
  if (!policy.enabled) return () => {};

  const run = () => {
    try {
      const result = runRuntimeFileCleanup(config);
      logger?.log("runtime_file_cleanup_completed", {
        dry_run: result.dry_run,
        scanned: result.scanned,
        candidates: result.candidates.length,
        deleted: result.deleted.length,
        skipped: result.skipped.length,
        errors: result.errors.length
      }, result.errors.length ? "warn" : "info");
      for (const error of result.errors) {
        logger?.log("runtime_file_cleanup_error", error, "warn");
      }
    } catch (error) {
      if (logger?.error) {
        logger.error("runtime_file_cleanup_failed", error);
      } else {
        logger?.log("runtime_file_cleanup_failed", { error_message: error instanceof Error ? error.message : String(error) }, "error");
      }
    }
  };

  if (policy.runOnStartup) run();
  const timer = setInterval(run, policy.intervalSeconds * 1000);
  timer.unref?.();
  return () => clearInterval(timer);
}
