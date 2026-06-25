import type { AppConfig } from "../types.js";
import type { MrSyncService } from "./MrSyncService.js";

interface SchedulerOptions {
  defaultPollIntervalSeconds?: number;
  logger?: Pick<typeof console, "log" | "error">;
}

export class MrAutoSyncScheduler {
  private readonly timers = new Map<string, NodeJS.Timeout>();
  private readonly inFlight = new Set<string>();
  private running = false;

  constructor(
    private readonly config: AppConfig,
    private readonly listProjectIds: () => string[],
    private readonly effectiveConfig: (projectId: string) => Promise<AppConfig>,
    private readonly mrSyncService: MrSyncService,
    private readonly options: SchedulerOptions = {}
  ) {}

  start() {
    if (this.running) return;
    this.running = true;
    void this.syncAllAndSchedule();
  }

  stop() {
    this.running = false;
    for (const timer of this.timers.values()) clearTimeout(timer);
    this.timers.clear();
  }

  async syncAllAndSchedule() {
    const projectIds = this.listProjectIds();
    for (const projectId of projectIds) {
      await this.syncProject(projectId);
      this.scheduleProject(projectId);
    }
  }

  private scheduleProject(projectId: string) {
    if (!this.running) return;
    void this.pollIntervalSeconds(projectId)
      .then((seconds) => {
        if (!this.running) return;
        const previous = this.timers.get(projectId);
        if (previous) clearTimeout(previous);
        const timer = setTimeout(async () => {
          await this.syncProject(projectId);
          this.scheduleProject(projectId);
        }, seconds * 1000);
        timer.unref?.();
        this.timers.set(projectId, timer);
      })
      .catch((error) => {
        this.options.logger?.error?.(`[auto-sync] project=${projectId} schedule failed: ${(error as Error).message}`);
      });
  }

  private async syncProject(projectId: string) {
    if (this.inFlight.has(projectId)) return;
    this.inFlight.add(projectId);
    try {
      const result = await this.mrSyncService.syncProject(projectId);
      this.options.logger?.log?.(`[auto-sync] project=${projectId} ${JSON.stringify(result)}`);
    } catch (error) {
      this.options.logger?.error?.(`[auto-sync] project=${projectId} failed: ${(error as Error).message}`);
    } finally {
      this.inFlight.delete(projectId);
    }
  }

  private async pollIntervalSeconds(projectId: string) {
    const effective = await this.effectiveConfig(projectId);
    const projectValue = Number(effective.queue_policy?.poll_interval_seconds);
    const defaultValue = Number(this.config.queue_policy?.poll_interval_seconds ?? this.options.defaultPollIntervalSeconds ?? 300);
    const interval = Number.isFinite(projectValue) && projectValue > 0 ? projectValue : defaultValue;
    return Math.max(15, Math.round(interval));
  }
}

export function shouldStartAutoSync() {
  return process.env.NODE_ENV !== "test" &&
    process.env.JOLT_AUTO_SYNC_DISABLED !== "1" &&
    process.env.JOLT_AUTO_SYNC_DISABLED !== "true";
}
