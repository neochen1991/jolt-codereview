import type { Db } from "../db.js";
import type { AppConfig } from "../types.js";
import type { ProjectConfigService } from "./ProjectConfigService.js";
import { projectMrConcurrency } from "./QueuePolicy.js";

const ACTIVE_REVIEW_STATUSES = "'fetching', 'pre_scanning', 'reviewing', 'judging', 'running'";

export function queuedReviewWorkerCapacity(input: {
  config: AppConfig;
  db: Db;
  projectConfigService: ProjectConfigService;
  maxAttempts?: number;
  maxWorkers?: number;
}) {
  const maxAttempts = input.maxAttempts ?? 3;
  const maxWorkers = input.maxWorkers ?? 20;
  const activeRows = input.db.prepare(`
    SELECT r.project_id, COUNT(*) AS count
    FROM review_jobs rj
    JOIN merge_requests mr ON mr.id = rj.merge_request_id
    JOIN repositories r ON r.id = mr.repository_id
    WHERE rj.status IN (${ACTIVE_REVIEW_STATUSES})
      AND COALESCE(rj.heartbeat_at, rj.locked_at, rj.updated_at) >= datetime('now', '-60 seconds')
    GROUP BY r.project_id
  `).all() as Array<{ project_id: string; count: number }>;
  const activeByProject = new Map(activeRows.map((row) => [String(row.project_id), Number(row.count || 0)]));
  const queuedRows = input.db.prepare(`
    SELECT r.project_id, COUNT(*) AS count
    FROM review_jobs rj
    JOIN merge_requests mr ON mr.id = rj.merge_request_id
    JOIN repositories r ON r.id = mr.repository_id
    WHERE rj.status = 'queued'
      AND rj.attempt < ?
    GROUP BY r.project_id
  `).all(maxAttempts) as Array<{ project_id: string; count: number }>;
  let capacity = 0;
  for (const row of queuedRows) {
    const projectId = String(row.project_id);
    const effectiveConfig = input.projectConfigService.effectiveConfig(projectId, input.config).effective_config;
    const projectCapacity = projectMrConcurrency(effectiveConfig);
    const activeCount = activeByProject.get(projectId) ?? 0;
    const available = Math.max(0, projectCapacity - activeCount);
    capacity += Math.min(Number(row.count || 0), available);
  }
  return Math.max(0, Math.min(maxWorkers, capacity));
}
