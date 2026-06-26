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
        ROUND(CAST(AVG(EXTRACT(EPOCH FROM NULLIF(rr.completed_at, '')::timestamptz) - EXTRACT(EPOCH FROM NULLIF(rr.started_at, '')::timestamptz)) AS NUMERIC), 2) AS avg_duration_seconds
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

  getReviewQualityMetrics(projectId: string, since?: string | null) {
    const params: unknown[] = [projectId];
    const sinceFilter = since ? "AND rf.created_at >= ?" : "";
    if (since) params.push(since);
    const rows = this.db.prepare(`
      SELECT
        rf.id,
        rf.severity,
        rf.lifecycle_state,
        rf.created_at,
        COALESCE(fb.accepted, 0) AS feedback_accepted,
        COALESCE(fb.false_positive, 0) AS feedback_false_positive
      FROM review_findings rf
      JOIN review_runs rr ON rr.id = rf.review_run_id
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      LEFT JOIN (
        SELECT
          finding_id,
          MAX(CASE WHEN feedback_type = 'accepted' THEN 1 ELSE 0 END) AS accepted,
          MAX(CASE WHEN feedback_type = 'false_positive' THEN 1 ELSE 0 END) AS false_positive
        FROM user_feedback
        GROUP BY finding_id
      ) fb ON fb.finding_id = rf.id
      WHERE r.project_id = ? ${sinceFilter}
      ORDER BY rf.created_at
    `).all(...params) as Array<{
      id: string;
      severity: string;
      lifecycle_state: string;
      created_at: string;
      feedback_accepted: number;
      feedback_false_positive: number;
    }>;

    const buckets = new Map<string, {
      week: string;
      published: number;
      accepted: number;
      false_positive: number;
      high_published: number;
      high_accepted: number;
    }>();
    for (const row of rows) {
      const week = isoWeekKey(row.created_at);
      const item = buckets.get(week) ?? {
        week,
        published: 0,
        accepted: 0,
        false_positive: 0,
        high_published: 0,
        high_accepted: 0
      };
      const accepted = row.lifecycle_state === "accepted" || Number(row.feedback_accepted || 0) > 0;
      const falsePositive = Number(row.feedback_false_positive || 0) > 0;
      const high = String(row.severity || "").toLowerCase() === "high" || String(row.severity || "").toLowerCase() === "critical";
      item.published += 1;
      if (accepted) item.accepted += 1;
      if (falsePositive) item.false_positive += 1;
      if (high) item.high_published += 1;
      if (high && accepted) item.high_accepted += 1;
      buckets.set(week, item);
    }

    const items = [...buckets.values()].map((item) => ({
      ...item,
      acceptance_rate: item.published ? Number((item.accepted / item.published).toFixed(4)) : null,
      false_positive_rate: item.published ? Number((item.false_positive / item.published).toFixed(4)) : null,
      high_severity_accuracy: item.high_published ? Number((item.high_accepted / item.high_published).toFixed(4)) : null
    }));
    const totals = items.reduce(
      (acc, item) => {
        acc.published += item.published;
        acc.accepted += item.accepted;
        acc.false_positive += item.false_positive;
        acc.high_published += item.high_published;
        acc.high_accepted += item.high_accepted;
        return acc;
      },
      { published: 0, accepted: 0, false_positive: 0, high_published: 0, high_accepted: 0 }
    );
    return {
      project_id: projectId,
      since: since || null,
      slo: {
        acceptance_rate_min: 0.4,
        false_positive_rate_max: 0.2,
        high_severity_accuracy_min: 0.6
      },
      totals: {
        ...totals,
        acceptance_rate: totals.published ? Number((totals.accepted / totals.published).toFixed(4)) : null,
        false_positive_rate: totals.published ? Number((totals.false_positive / totals.published).toFixed(4)) : null,
        high_severity_accuracy: totals.high_published ? Number((totals.high_accepted / totals.high_published).toFixed(4)) : null
      },
      items
    };
  }
}

function isoWeekKey(value: string | null | undefined) {
  const raw = String(value || "").trim();
  const date = raw ? new Date(raw.replace(" ", "T")) : new Date();
  const safeDate = Number.isNaN(date.getTime()) ? new Date() : date;
  const utc = new Date(Date.UTC(safeDate.getFullYear(), safeDate.getMonth(), safeDate.getDate()));
  const day = utc.getUTCDay() || 7;
  utc.setUTCDate(utc.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(utc.getUTCFullYear(), 0, 1));
  const week = Math.ceil((((utc.getTime() - yearStart.getTime()) / 86400000) + 1) / 7);
  return `${utc.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}
