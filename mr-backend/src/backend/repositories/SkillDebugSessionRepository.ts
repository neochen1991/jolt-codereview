import type { Db } from "../db.js";

export interface CreateSkillDebugSessionInput {
  id: string;
  projectId: string;
  repositoryId: string;
  mergeRequestId: string;
  headSha: string;
  skillKey: string;
  skillVersion: string;
  agentKey: string;
  mode: "targeted" | "production_route";
  effortLevel: string;
  requestedBy: string;
  snapshot: Record<string, unknown>;
  snapshotSha256: string;
  expiresAt?: string | null;
}

export class SkillDebugSessionRepository {
  constructor(private readonly db: Db) {}

  create(input: CreateSkillDebugSessionInput) {
    this.db.prepare(`
      INSERT INTO skill_debug_sessions (
        id, project_id, repository_id, merge_request_id, head_sha,
        skill_key, skill_version, agent_key, mode, status,
        requested_effort_level, requested_by, snapshot_json, snapshot_sha256, expires_at
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'queued', $10, $11, $12, $13, $14)
    `).run(
      input.id, input.projectId, input.repositoryId, input.mergeRequestId, input.headSha,
      input.skillKey, input.skillVersion, input.agentKey, input.mode, input.effortLevel,
      input.requestedBy, JSON.stringify(input.snapshot), input.snapshotSha256, input.expiresAt ?? null
    );
    return this.findById(input.id);
  }

  findById(sessionId: string) {
    return this.db.prepare("SELECT * FROM skill_debug_sessions WHERE id = $1").get(sessionId);
  }

  listByProject(projectId: string, limit = 50) {
    return this.db.prepare(`
      SELECT s.*, mr.title AS mr_title
      FROM skill_debug_sessions s
      JOIN merge_requests mr ON mr.id = s.merge_request_id
      WHERE s.project_id = $1
      ORDER BY s.created_at DESC
      LIMIT $2
    `).all(projectId, limit);
  }

  attachJobs(sessionId: string, baselineJobId: string | null, candidateJobId: string) {
    this.db.prepare(`
      UPDATE skill_debug_sessions
      SET baseline_job_id = $1, candidate_job_id = $2, updated_at = CURRENT_TIMESTAMP
      WHERE id = $3
    `).run(baselineJobId, candidateJobId, sessionId);
    return this.findById(sessionId);
  }

  updateStatus(sessionId: string, status: string, failureReason?: string | null) {
    this.db.prepare(`
      UPDATE skill_debug_sessions
      SET status = $1,
          failure_reason = $2,
          cancelled_at = CASE WHEN $1 = 'cancelled' THEN CURRENT_TIMESTAMP ELSE cancelled_at END,
          updated_at = CURRENT_TIMESTAMP
      WHERE id = $3
    `).run(status, failureReason ?? null, sessionId);
    return this.findById(sessionId);
  }

  updateComparison(sessionId: string, comparison: Record<string, unknown>) {
    this.db.prepare(`
      UPDATE skill_debug_sessions
      SET comparison_json = $1, updated_at = CURRENT_TIMESTAMP
      WHERE id = $2
    `).run(JSON.stringify(comparison), sessionId);
    return this.findById(sessionId);
  }

  expireDue() {
    return this.db.prepare(`
      UPDATE skill_debug_sessions
      SET status = 'expired', snapshot_json = '{}', comparison_json = '{}', updated_at = CURRENT_TIMESTAMP
      WHERE expires_at IS NOT NULL
        AND expires_at::timestamptz < CURRENT_TIMESTAMP
        AND status <> 'expired'
    `).run();
  }
}
