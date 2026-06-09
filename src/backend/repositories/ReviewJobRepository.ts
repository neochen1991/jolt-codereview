import type { Db } from "../db.js";

export class ReviewJobRepository {
  constructor(private readonly db: Db) {}

  findById(jobId: string) {
    return this.db.prepare("SELECT * FROM review_jobs WHERE id = ?").get(jobId);
  }

  enqueueIgnore(input: {
    id: string;
    mergeRequestId: string;
    headSha: string;
    priority: number;
    effortLevel?: string;
    requestedBy?: string | null;
  }) {
    return this.db.prepare(`
      INSERT OR IGNORE INTO review_jobs (id, merge_request_id, head_sha, status, priority, requested_effort_level, requested_by)
      VALUES (?, ?, ?, 'queued', ?, ?, ?)
    `).run(input.id, input.mergeRequestId, input.headSha, input.priority, input.effortLevel ?? "standard", input.requestedBy ?? null);
  }

  enqueueOrReset(input: {
    id: string;
    mergeRequestId: string;
    headSha: string;
    priority: number;
    effortLevel: string;
    requestedBy?: string | null;
  }) {
    this.db.prepare(`
      INSERT INTO review_jobs (id, merge_request_id, head_sha, status, priority, requested_effort_level, requested_by)
      VALUES (?, ?, ?, 'queued', ?, ?, ?)
      ON CONFLICT(merge_request_id, head_sha) DO UPDATE SET
        status = 'queued',
        requested_effort_level = excluded.requested_effort_level,
        requested_by = COALESCE(excluded.requested_by, review_jobs.requested_by),
        attempt = 0,
        locked_at = NULL,
        locked_by = NULL,
        heartbeat_at = NULL,
        updated_at = CURRENT_TIMESTAMP
    `).run(input.id, input.mergeRequestId, input.headSha, input.priority, input.effortLevel, input.requestedBy ?? null);
  }

  supersedeQueued(mergeRequestId: string) {
    return this.db.prepare("UPDATE review_jobs SET status = 'superseded', updated_at = CURRENT_TIMESTAMP WHERE merge_request_id = ? AND status = 'queued'").run(mergeRequestId);
  }

  cancelQueued(mergeRequestId: string) {
    return this.db.prepare("UPDATE review_jobs SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE merge_request_id = ? AND status = 'queued'").run(mergeRequestId);
  }

  pauseByMergeRequest(mergeRequestId: string) {
    return this.db.prepare(`
      UPDATE review_jobs
      SET status = 'paused',
          updated_at = CURRENT_TIMESTAMP
      WHERE merge_request_id = ?
        AND status IN ('queued', 'fetching', 'pre_scanning', 'reviewing', 'judging', 'running')
    `).run(mergeRequestId);
  }

  stopByMergeRequest(mergeRequestId: string) {
    return this.db.prepare(`
      UPDATE review_jobs
      SET status = 'cancelled',
          locked_at = NULL,
          locked_by = NULL,
          heartbeat_at = NULL,
          updated_at = CURRENT_TIMESTAMP
      WHERE merge_request_id = ?
        AND status IN ('queued', 'paused', 'fetching', 'pre_scanning', 'reviewing', 'judging', 'running')
    `).run(mergeRequestId);
  }

  listByMergeRequest(mergeRequestId: string) {
    return this.db.prepare("SELECT * FROM review_jobs WHERE merge_request_id = ? ORDER BY created_at DESC").all(mergeRequestId);
  }

  findByMergeRequestAndHead(mergeRequestId: string, headSha: string) {
    return this.db.prepare("SELECT * FROM review_jobs WHERE merge_request_id = ? AND head_sha = ?").get(mergeRequestId, headSha);
  }

  findWithProject(jobId: string) {
    return this.db.prepare(`
      SELECT rj.*, r.project_id
      FROM review_jobs rj
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      WHERE rj.id = ?
    `).get(jobId);
  }

  retry(jobId: string, effortLevel: string, requestedBy?: string | null) {
    this.db.prepare(`
      UPDATE review_jobs
      SET status = 'queued',
          requested_effort_level = ?,
          requested_by = COALESCE(?, requested_by),
          attempt = 0,
          locked_at = NULL,
          locked_by = NULL,
          heartbeat_at = NULL,
          updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
    `).run(effortLevel, requestedBy ?? null, jobId);
  }

  deadLetter(jobId: string, reason: string, finalAttempt: number, deadLetterId: string) {
    this.db.prepare(`
      INSERT INTO review_jobs_dead_letter (id, review_job_id, failure_reason, final_attempt)
      VALUES (?, ?, ?, ?)
    `).run(deadLetterId, jobId, reason, finalAttempt);
    this.db.prepare(`
      UPDATE review_jobs
      SET status = 'dead_letter',
          attempt = ?,
          locked_at = NULL,
          locked_by = NULL,
          heartbeat_at = NULL,
          updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
    `).run(finalAttempt, jobId);
  }

  reclaimStale(seconds: number) {
    return this.db.prepare(`
      UPDATE review_jobs
      SET status = 'queued', locked_at = NULL, locked_by = NULL, updated_at = CURRENT_TIMESTAMP
      WHERE status IN ('fetching', 'pre_scanning', 'reviewing', 'judging')
        AND (heartbeat_at IS NULL OR heartbeat_at < datetime('now', ?))
    `).run(`-${seconds} seconds`);
  }
}
