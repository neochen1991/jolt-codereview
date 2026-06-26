import type { ChildProcess } from "node:child_process";
import type { Db } from "../db.js";
import type { AppConfig } from "../types.js";
import { projectMrConcurrency } from "./QueuePolicy.js";
import { spawnWorkerLoop, type WorkerProcessLogger } from "./WorkerProcessLauncher.js";

function positiveInt(value: unknown, fallback: number, min = 1, max = 20) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return fallback;
  return Math.max(min, Math.min(max, Math.floor(number)));
}

export class WorkerPoolManager {
  private readonly workers = new Map<number, ChildProcess>();
  private timer: NodeJS.Timeout | null = null;

  constructor(private readonly input: {
    config: AppConfig;
    db: Db;
    logger?: WorkerProcessLogger;
    effectiveConfig(projectId: string): Promise<AppConfig>;
  }) {}

  start() {
    void this.reconcile("startup");
    const intervalSeconds = positiveInt(
      process.env.MR_WORKER_RECONCILE_SECONDS ?? this.input.config.queue_policy?.worker_reconcile_seconds,
      30,
      5,
      3600
    );
    this.timer = setInterval(() => void this.reconcile("interval"), intervalSeconds * 1000);
    this.timer.unref?.();
  }

  stop() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    for (const child of this.workers.values()) {
      if (!child.killed) child.kill();
    }
    this.workers.clear();
  }

  async reconcile(reason = "manual") {
    this.pruneExited();
    const desired = await this.desiredWorkerCount();
    const current = this.workers.size;
    if (current >= desired) {
      this.input.logger?.log("worker_pool_reconciled", { reason, desired, current });
      return { desired, current, spawned: 0 };
    }
    const spawnCount = desired - current;
    for (let index = 0; index < spawnCount; index += 1) {
      this.spawnLoopWorker(reason);
    }
    this.input.logger?.log("worker_pool_reconciled", {
      reason,
      desired,
      current,
      spawned: spawnCount
    });
    return { desired, current, spawned: spawnCount };
  }

  private spawnLoopWorker(reason: string) {
    const child = spawnWorkerLoop(this.input.logger);
    if (child.pid) this.workers.set(child.pid, child);
    child.on("exit", (code, signal) => {
      if (child.pid) this.workers.delete(child.pid);
      this.input.logger?.log("worker_loop_exited", {
        pid: child.pid ?? null,
        reason,
        code,
        signal
      }, code || signal ? "warn" : "info");
    });
  }

  private pruneExited() {
    for (const [pid, child] of this.workers) {
      if (child.exitCode !== null || child.killed) this.workers.delete(pid);
    }
  }

  private async desiredWorkerCount() {
    const base = positiveInt(
      process.env.MR_WORKER_COUNT ?? this.input.config.queue_policy?.worker_pool_size,
      1
    );
    const max = positiveInt(
      process.env.MR_WORKER_MAX ?? this.input.config.queue_policy?.max_worker_pool_size,
      20
    );
    const projects = this.input.db.prepare(`
      SELECT DISTINCT project_id
      FROM repositories
      WHERE status = 'active'
    `).all() as Array<{ project_id: string }>;
    if (!projects.length) return Math.min(base, max);
    let capacity = 0;
    for (const row of projects) {
      const projectId = String(row.project_id);
      try {
        const effective = await this.input.effectiveConfig(projectId);
        capacity += projectMrConcurrency(effective);
      } catch (error) {
        capacity += projectMrConcurrency(this.input.config);
        this.input.logger?.error?.("worker_pool_project_config_failed", error, { project_id: projectId });
      }
    }
    return Math.min(max, Math.max(base, capacity));
  }
}
