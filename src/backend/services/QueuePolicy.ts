import type { AppConfig } from "../types.js";

export const DEFAULT_PROJECT_MR_CONCURRENCY = 1;

export function projectMrConcurrency(config?: AppConfig): number {
  const value = Number(config?.queue_policy?.max_concurrency);
  if (!Number.isFinite(value) || value <= 0) return DEFAULT_PROJECT_MR_CONCURRENCY;
  return Math.max(1, Math.min(20, Math.floor(value)));
}
