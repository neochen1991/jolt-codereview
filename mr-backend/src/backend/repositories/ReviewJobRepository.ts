import type { Db } from "../db.js";

export class ReviewJobRepository {
  constructor(private readonly db: Db) {}

  findById(jobId: string) {
    return this.db.prepare("SELECT * FROM review_jobs WHERE id = $1").get(jobId);
  }

  enqueueIgnore(input: {
    id: string;
    mergeRequestId: string;
    headSha: string;
    priority: number;
    effortLevel?: string;
    requestedBy?: string | null;
    debugContext?: Record<string, unknown> | null;
  }) {
    return this.db.prepare(`
      INSERT INTO review_jobs (id, merge_request_id, head_sha, status, priority, requested_effort_level, requested_by, debug_context_json)
      VALUES ($1, $2, $3, 'queued', $4, $5, $6, $7)
      ON CONFLICT (merge_request_id, head_sha) WHERE execution_kind = 'production_review' DO NOTHING
    `).run(input.id, input.mergeRequestId, input.headSha, input.priority, input.effortLevel ?? "standard", input.requestedBy ?? null, JSON.stringify(input.debugContext ?? {}));
  }

  enqueueOrReset(input: {
    id: string;
    mergeRequestId: string;
    headSha: string;
    priority: number;
    effortLevel: string;
    requestedBy?: string | null;
    debugContext?: Record<string, unknown> | null;
  }) {
    this.db.prepare(`
      INSERT INTO review_jobs (id, merge_request_id, head_sha, status, priority, requested_effort_level, requested_by, debug_context_json)
      VALUES ($1, $2, $3, 'queued', $4, $5, $6, $7)
      ON CONFLICT(merge_request_id, head_sha) WHERE execution_kind = 'production_review' DO UPDATE SET
        status = 'queued',
        requested_effort_level = excluded.requested_effort_level,
        requested_by = COALESCE(excluded.requested_by, review_jobs.requested_by),
        debug_context_json = excluded.debug_context_json,
        attempt = 0,
        locked_at = NULL,
        locked_by = NULL,
        heartbeat_at = NULL,
        updated_at = CURRENT_TIMESTAMP
    `).run(input.id, input.mergeRequestId, input.headSha, input.priority, input.effortLevel, input.requestedBy ?? null, JSON.stringify(input.debugContext ?? {}));
  }

  enqueueDebug(input: {
    id: string;
    mergeRequestId: string;
    headSha: string;
    priority: number;
    effortLevel: string;
    requestedBy: string;
    debugSessionId: string;
    debugVariant: "baseline" | "candidate";
    debugContext: Record<string, unknown>;
  }) {
    this.db.prepare(`
      INSERT INTO review_jobs (
        id, merge_request_id, head_sha, status, priority, requested_effort_level,
        requested_by, debug_context_json, execution_kind, debug_session_id, debug_variant
      ) VALUES ($1, $2, $3, 'queued', $4, $5, $6, $7, $8, $9, $10)
    `).run(
      input.id, input.mergeRequestId, input.headSha, input.priority, input.effortLevel,
      input.requestedBy, JSON.stringify(input.debugContext), `skill_debug_${input.debugVariant}`,
      input.debugSessionId, input.debugVariant
    );
    return this.findById(input.id);
  }

  supersedeQueued(mergeRequestId: string) {
    return this.db.prepare("UPDATE review_jobs SET status = 'superseded', updated_at = CURRENT_TIMESTAMP WHERE merge_request_id = $1 AND status = 'queued'").run(mergeRequestId);
  }

  cancelQueued(mergeRequestId: string) {
    return this.db.prepare("UPDATE review_jobs SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE merge_request_id = $1 AND status = 'queued'").run(mergeRequestId);
  }

  pauseByMergeRequest(mergeRequestId: string) {
    return this.db.prepare(`
      UPDATE review_jobs
      SET status = 'paused',
          updated_at = CURRENT_TIMESTAMP
      WHERE merge_request_id = $1
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
      WHERE merge_request_id = $1
        AND status IN ('queued', 'paused', 'fetching', 'pre_scanning', 'reviewing', 'judging', 'running')
    `).run(mergeRequestId);
  }

  listByMergeRequest(mergeRequestId: string) {
    return this.db.prepare("SELECT * FROM review_jobs WHERE merge_request_id = $1 AND execution_kind = 'production_review' ORDER BY created_at DESC").all(mergeRequestId);
  }

  findByMergeRequestAndHead(mergeRequestId: string, headSha: string) {
    return this.db.prepare("SELECT * FROM review_jobs WHERE merge_request_id = $1 AND head_sha = $2 AND execution_kind = 'production_review'").get(mergeRequestId, headSha);
  }

  findWithProject(jobId: string) {
    return this.db.prepare(`
      SELECT rj.*, r.project_id
      FROM review_jobs rj
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      WHERE rj.id = $1
    `).get(jobId);
  }

  retry(jobId: string, effortLevel: string, requestedBy?: string | null) {
    this.db.prepare(`
      UPDATE review_jobs
      SET status = 'queued',
          requested_effort_level = $1,
          requested_by = COALESCE($2, requested_by),
          attempt = 0,
          locked_at = NULL,
          locked_by = NULL,
          heartbeat_at = NULL,
          updated_at = CURRENT_TIMESTAMP
      WHERE id = $3
    `).run(effortLevel, requestedBy ?? null, jobId);
  }

  deadLetter(jobId: string, reason: string, finalAttempt: number, deadLetterId: string) {
    this.db.prepare(`
      INSERT INTO review_jobs_dead_letter (id, review_job_id, failure_reason, final_attempt)
      VALUES ($1, $2, $3, $4)
    `).run(deadLetterId, jobId, reason, finalAttempt);
    this.db.prepare(`
      UPDATE review_jobs
      SET status = 'dead_letter',
          attempt = $1,
          locked_at = NULL,
          locked_by = NULL,
          heartbeat_at = NULL,
          updated_at = CURRENT_TIMESTAMP
      WHERE id = $2
    `).run(finalAttempt, jobId);
  }

  reclaimStale(seconds: number) {
    return this.db.prepare(`
      UPDATE review_jobs
      SET status = 'queued', locked_at = NULL, locked_by = NULL, updated_at = CURRENT_TIMESTAMP
      WHERE status IN ('fetching', 'pre_scanning', 'reviewing', 'judging')
        AND (heartbeat_at IS NULL OR NULLIF(heartbeat_at, '')::timestamptz < CURRENT_TIMESTAMP - ($1 * INTERVAL '1 second'))
    `).run(seconds);
  }
}
