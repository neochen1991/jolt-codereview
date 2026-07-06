import { existsSync, lstatSync, readdirSync, rmSync, statSync } from "node:fs";
import path from "node:path";
import type { AppConfig } from "../types.js";

type CleanupReason = "max_age" | "max_log_size" | "max_total_size";

export interface CleanupItem {
  path: string;
  kind: "file" | "dir";
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
  kind: "file" | "dir";
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
    maxTotalMb: Math.max(0, Number(policy.max_total_mb ?? 10240)),
    maxLogFileMb: Math.max(0, Number(policy.max_log_file_mb ?? 512))
  };
}

function loggingConfig(config: AppConfig) {
  const logging = config.logging || {};
  return {
    enabled: logging.enabled ?? true,
    dir: logging.dir || "logs",
    reviewRunDir: logging.review_run_dir || "review-runs"
  };
}

function isInside(parent: string, child: string): boolean {
  const relative = path.relative(parent, child);
  return relative === "" || (!!relative && !relative.startsWith("..") && !path.isAbsolute(relative));
}

function safeResolve(root: string, value: string): string {
  const resolved = path.isAbsolute(value) ? path.resolve(value) : path.resolve(root, value);
  if (!isInside(root, resolved)) {
    throw new Error(`cleanup path escapes service root: ${value}`);
  }
  return resolved;
}

function fileSize(target: string): number {
  try {
    return statSync(target).size;
  } catch {
    return 0;
  }
}

function dirSize(target: string): number {
  let total = 0;
  for (const entry of readdirSync(target, { withFileTypes: true })) {
    const child = path.join(target, entry.name);
    if (entry.isSymbolicLink()) continue;
    if (entry.isDirectory()) {
      total += dirSize(child);
    } else if (entry.isFile()) {
      total += fileSize(child);
    }
  }
  return total;
}

function targetInfo(target: string, kind: "file" | "dir"): CleanupTarget | null {
  try {
    const stat = statSync(target);
    return {
      path: target,
      kind,
      size_bytes: kind === "dir" ? dirSize(target) : stat.size,
      mtime_ms: stat.mtimeMs
    };
  } catch {
    return null;
  }
}

function collectLogFiles(logDir: string): CleanupTarget[] {
  if (!existsSync(logDir)) return [];
  const items: CleanupTarget[] = [];
  for (const entry of readdirSync(logDir, { withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith(".log")) continue;
    const info = targetInfo(path.join(logDir, entry.name), "file");
    if (info) items.push(info);
  }
  return items;
}

function collectReviewRunLogs(reviewRunDir: string): CleanupTarget[] {
  if (!existsSync(reviewRunDir)) return [];
  const items: CleanupTarget[] = [];
  for (const entry of readdirSync(reviewRunDir, { withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith(".jsonl")) continue;
    const info = targetInfo(path.join(reviewRunDir, entry.name), "file");
    if (info) items.push(info);
  }
  return items;
}

function collectSandboxes(sandboxDir: string): CleanupTarget[] {
  if (!existsSync(sandboxDir)) return [];
  const items: CleanupTarget[] = [];
  for (const entry of readdirSync(sandboxDir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const info = targetInfo(path.join(sandboxDir, entry.name), "dir");
    if (info) items.push(info);
  }
  return items;
}

function addCandidate(candidates: Map<string, CleanupItem>, target: CleanupTarget, reason: CleanupReason) {
  const existing = candidates.get(target.path);
  if (existing) return;
  candidates.set(target.path, { ...target, reason });
}

export function runRuntimeFileCleanup(config: AppConfig, options: CleanupOptions = {}): RuntimeCleanupResult {
  const policy = cleanupPolicy(config);
  const result: RuntimeCleanupResult = { dry_run: !!options.dryRun, scanned: 0, candidates: [], deleted: [], skipped: [], errors: [] };
  if (!policy.enabled) return result;

  const root = path.resolve(options.serviceRoot || process.cwd());
  const logging = loggingConfig(config);
  if (!logging.enabled) return result;

  let logDir: string;
  let reviewRunDir: string;
  let sandboxDir: string;
  try {
    logDir = safeResolve(root, logging.dir);
    reviewRunDir = safeResolve(logDir, logging.reviewRunDir);
    sandboxDir = safeResolve(root, path.join("worker", "data", "sandboxes"));
  } catch (error) {
    result.errors.push({ path: root, message: error instanceof Error ? error.message : String(error) });
    return result;
  }
  const allowedRoots = [logDir, sandboxDir];
  const now = options.now ?? Date.now();
  const cutoff = now - policy.maxAgeDays * 24 * 60 * 60 * 1000;
  const maxTotalBytes = policy.maxTotalMb * 1024 * 1024;
  const maxLogFileBytes = policy.maxLogFileMb * 1024 * 1024;
  const targets = [
    ...collectLogFiles(logDir),
    ...collectReviewRunLogs(reviewRunDir),
    ...collectSandboxes(sandboxDir)
  ].filter((target) => allowedRoots.some((allowed) => isInside(allowed, target.path)));
  result.scanned = targets.length;

  const candidates = new Map<string, CleanupItem>();
  for (const target of targets) {
    if (target.mtime_ms < cutoff) {
      addCandidate(candidates, target, "max_age");
    } else if (maxLogFileBytes > 0 && target.kind === "file" && target.path.endsWith(".log") && target.size_bytes > maxLogFileBytes) {
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
    if (!allowedRoots.some((allowed) => isInside(allowed, item.path))) {
      result.skipped.push({ path: item.path, reason: "not_under_allowed_runtime_root" });
      continue;
    }
    try {
      const stat = lstatSync(item.path);
      if (stat.isSymbolicLink()) {
        result.skipped.push({ path: item.path, reason: "symbolic_link" });
        continue;
      }
      rmSync(item.path, { recursive: item.kind === "dir", force: true });
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
