import type { Db } from "../db.js";

function parseJson(value: string | null | undefined) {
  if (!value) return {};
  try {
    return JSON.parse(value);
  } catch {
    return {};
  }
}

export class ObservabilityService {
  constructor(private readonly db: Db) {}

  queueSummary(projectId: string) {
    const byStatus = this.db.prepare(`
      SELECT rj.status, COUNT(*) AS count
      FROM review_jobs rj
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      WHERE r.project_id = ?
      GROUP BY rj.status
      ORDER BY rj.status
    `).all(projectId);
    const running = this.db.prepare(`
      SELECT rj.id, rj.status, rj.attempt, rj.locked_at, rj.heartbeat_at, mr.title, mr.number, r.name AS repository_name
      FROM review_jobs rj
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      WHERE r.project_id = ? AND rj.status IN ('fetching', 'pre_scanning', 'reviewing', 'judging')
      ORDER BY rj.locked_at DESC
      LIMIT 20
    `).all(projectId);
    const deadLetters = this.db.prepare(`
      SELECT COUNT(*) AS count
      FROM review_jobs_dead_letter dl
      JOIN review_jobs rj ON rj.id = dl.review_job_id
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      WHERE r.project_id = ?
    `).get(projectId) as { count: number } | undefined;
    const duration = this.db.prepare(`
      SELECT
        COUNT(*) AS completed_runs,
        ROUND(CAST(AVG((julianday(rr.completed_at) - julianday(rr.started_at)) * 86400) AS NUMERIC), 2) AS avg_duration_seconds
      FROM review_runs rr
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      WHERE r.project_id = ? AND rr.completed_at IS NOT NULL
    `).get(projectId);
    return {
      project_id: projectId,
      by_status: byStatus,
      running,
      dead_letter_count: deadLetters?.count ?? 0,
      duration
    };
  }

  toolchainStatus(projectId: string) {
    const toolCalls = this.db.prepare(`
      SELECT t.tool_name, t.status, COUNT(*) AS count, MAX(t.created_at) AS last_seen_at
      FROM tool_call_records t
      JOIN agent_trace_spans s ON s.id = t.span_id
      JOIN review_runs rr ON rr.id = s.review_run_id
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      WHERE r.project_id = ?
      GROUP BY t.tool_name, t.status
      ORDER BY t.tool_name, t.status
    `).all(projectId);
    const latestRun = this.db.prepare(`
      SELECT rr.id, rr.toolchain_manifest
      FROM review_runs rr
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      WHERE r.project_id = ?
      ORDER BY rr.started_at DESC
      LIMIT 1
    `).get(projectId) as { id: string; toolchain_manifest: string } | undefined;
    return {
      project_id: projectId,
      latest_run_id: latestRun?.id ?? null,
      latest_manifest: parseJson(latestRun?.toolchain_manifest),
      tool_calls: toolCalls
    };
  }

  agentQuality(projectId: string) {
    const items = this.db.prepare(`
      SELECT
        rf.agent_id,
        COUNT(*) AS finding_count,
        ROUND(CAST(AVG(rf.confidence) AS NUMERIC), 3) AS avg_confidence,
        SUM(CASE WHEN rf.lifecycle_state = 'accepted' THEN 1 ELSE 0 END) AS accepted_count,
        SUM(CASE WHEN uf.feedback_type = 'false_positive' THEN 1 ELSE 0 END) AS false_positive_count,
        ROUND(CAST(1.0 * SUM(CASE WHEN uf.feedback_type = 'false_positive' THEN 1 ELSE 0 END) / COUNT(*) AS NUMERIC), 3) AS false_positive_rate
      FROM review_findings rf
      JOIN review_runs rr ON rr.id = rf.review_run_id
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      LEFT JOIN user_feedback uf ON uf.finding_id = rf.id
      WHERE r.project_id = ?
      GROUP BY rf.agent_id
      ORDER BY finding_count DESC, rf.agent_id
    `).all(projectId);
    return { project_id: projectId, items };
  }
}
