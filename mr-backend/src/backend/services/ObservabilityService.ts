import type { Db } from "../db.js";

function parseJson(value: string | null | undefined) {
  if (!value) return {};
  try {
    return JSON.parse(value);
  } catch {
    return {};
  }
}

function numberValue(value: unknown) {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function nullableNumberValue(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function coveragePayload(row: { coverage_json?: string | null }) {
  const coverage = parseJson(row.coverage_json);
  const candidateQuality = typeof coverage.candidate_quality === "object" && coverage.candidate_quality ? coverage.candidate_quality as Record<string, unknown> : {};
  const payload = candidateQuality.bound_review_coverage ?? coverage.bound_review_coverage;
  return typeof payload === "object" && payload ? payload as Record<string, unknown> : null;
}

export function summarizeBoundRuleCoverage(rows: Array<{ coverage_json?: string | null }>) {
  const missed: Array<Record<string, unknown>> = [];
  const totals = rows.reduce(
    (acc, row) => {
      const payload = coveragePayload(row);
      if (!payload) return acc;
      const required = numberValue(payload.required_count);
      if (!required) return acc;
      acc.run_count += 1;
      acc.required_count += required;
      acc.checked_count += numberValue(payload.checked_count);
      acc.hit_count += numberValue(payload.hit_count);
      acc.skipped_count += numberValue(payload.skipped_count);
      acc.missed_count += numberValue(payload.missed_count);
      acc.resolved_count += numberValue(payload.resolved_count) || (numberValue(payload.hit_count) + numberValue(payload.skipped_count));
      acc.unresolved_count += numberValue(payload.unresolved_count) || numberValue(payload.missed_count);
      acc.rule_count += numberValue(payload.rule_count);
      acc.skill_checkpoint_count += numberValue(payload.skill_checkpoint_count);
      acc.rejected_count += numberValue(payload.rejected_count);
      if (numberValue(payload.coverage_rate) < 0.7) acc.low_coverage_run_count += 1;
      const resolutionRate = nullableNumberValue(payload.resolution_rate);
      if ((resolutionRate ?? ((numberValue(payload.hit_count) + numberValue(payload.skipped_count)) / required)) < 0.7) {
        acc.low_resolution_run_count += 1;
      }
      const missedItems = Array.isArray(payload.missed) ? payload.missed : [];
      for (const item of missedItems) {
        if (missed.length >= 20 || typeof item !== "object" || !item) continue;
        missed.push(item as Record<string, unknown>);
      }
      return acc;
    },
    {
      run_count: 0,
      required_count: 0,
      checked_count: 0,
      hit_count: 0,
      skipped_count: 0,
      missed_count: 0,
      resolved_count: 0,
      unresolved_count: 0,
      rule_count: 0,
      skill_checkpoint_count: 0,
      rejected_count: 0,
      low_coverage_run_count: 0,
      low_resolution_run_count: 0
    }
  );
  return {
    ...totals,
    coverage_rate: totals.required_count ? Number((totals.checked_count / totals.required_count).toFixed(4)) : null,
    resolution_rate: totals.required_count ? Number((totals.resolved_count / totals.required_count).toFixed(4)) : null,
    unresolved_rate: totals.required_count ? Number((totals.unresolved_count / totals.required_count).toFixed(4)) : null,
    hit_rate: totals.required_count ? Number((totals.hit_count / totals.required_count).toFixed(4)) : null,
    skip_rate: totals.required_count ? Number((totals.skipped_count / totals.required_count).toFixed(4)) : null,
    missed
  };
}

function emptyAgentCoverage(agentId: string) {
  return {
    agent_id: agentId,
    required_count: 0,
    checked_count: 0,
    hit_count: 0,
    skipped_count: 0,
    missed_count: 0,
    resolved_count: 0,
    unresolved_count: 0,
    rejected_count: 0,
    resolution_rate: null as number | null,
    unresolved_rate: null as number | null
  };
}

type SkillCheckpointMetric = {
  project_id: string;
  skill_key: string;
  checkpoint_id: string;
  agent_id: string;
  model: string;
  week: string;
  checked_count: number;
  hit_count: number;
  skip_count: number;
  retry_count: number;
  retry_hit_count: number;
  rejected_count: number;
  manual_accept_count: number;
  manual_reject_count: number;
  duplicate_merge_count: number;
};

function emptySkillCheckpointMetric(
  projectId: string,
  skillKey: string,
  checkpointId: string,
  agentId: string,
  model: string,
  week: string
): SkillCheckpointMetric {
  return {
    project_id: projectId,
    skill_key: skillKey,
    checkpoint_id: checkpointId,
    agent_id: agentId,
    model,
    week,
    checked_count: 0,
    hit_count: 0,
    skip_count: 0,
    retry_count: 0,
    retry_hit_count: 0,
    rejected_count: 0,
    manual_accept_count: 0,
    manual_reject_count: 0,
    duplicate_merge_count: 0
  };
}

function skillCheckpointMetricKey(item: Pick<SkillCheckpointMetric, "project_id" | "skill_key" | "checkpoint_id" | "agent_id" | "model" | "week">) {
  return [item.project_id, item.skill_key, item.checkpoint_id, item.agent_id, item.model, item.week].join("\u0001");
}

export function summarizeBoundRuleCoverageByAgent(rows: Array<{ coverage_json?: string | null }>) {
  const byAgent = new Map<string, ReturnType<typeof emptyAgentCoverage>>();
  for (const row of rows) {
    const payload = coveragePayload(row);
    const items = Array.isArray(payload?.items) ? payload.items : [];
    for (const rawItem of items) {
      if (typeof rawItem !== "object" || !rawItem) continue;
      const item = rawItem as Record<string, unknown>;
      if (!["rule", "skill_checkpoint"].includes(String(item.type || ""))) continue;
      const agentId = String(item.agent_id || "").trim();
      if (!agentId) continue;
      const current = byAgent.get(agentId) ?? emptyAgentCoverage(agentId);
      current.required_count += 1;
      if (item.checked) current.checked_count += 1;
      const findingCount = numberValue(item.finding_count);
      const skipped = Boolean(item.skipped);
      if (findingCount > 0) current.hit_count += 1;
      if (skipped) current.skipped_count += 1;
      if (item.checked && findingCount === 0 && !skipped) current.missed_count += 1;
      current.rejected_count += numberValue(item.rejected_count);
      byAgent.set(agentId, current);
    }
  }
  return [...byAgent.values()]
    .map((item) => {
      const resolved = item.hit_count + item.skipped_count;
      const unresolved = item.missed_count;
      return {
        ...item,
        resolved_count: resolved,
        unresolved_count: unresolved,
        resolution_rate: item.required_count ? Number((resolved / item.required_count).toFixed(4)) : null,
        unresolved_rate: item.required_count ? Number((unresolved / item.required_count).toFixed(4)) : null
      };
    })
    .sort((left, right) => left.agent_id.localeCompare(right.agent_id));
}

export function summarizeSkillCheckpointMetrics(
  projectId: string,
  rows: Array<{ id: string; started_at?: string | null; coverage_json?: string | null }>,
  modelByRunAgent: Map<string, string>
) {
  const byKey = new Map<string, SkillCheckpointMetric>();
  for (const row of rows) {
    const payload = coveragePayload(row);
    const items = Array.isArray(payload?.items) ? payload.items : [];
    for (const rawItem of items) {
      if (typeof rawItem !== "object" || !rawItem) continue;
      const item = rawItem as Record<string, unknown>;
      if (String(item.type || "") !== "skill_checkpoint") continue;
      const skillKey = String(item.skill_key || "skill_bundle").trim();
      const checkpointId = String(item.checkpoint_id || item.rule_id || "").trim();
      const agentId = String(item.agent_id || "").trim();
      if (!skillKey || !checkpointId || !agentId) continue;
      const model = modelByRunAgent.get(`${row.id}:${agentId}`) || "unknown";
      const week = isoWeekKey(row.started_at);
      const key = skillCheckpointMetricKey({ project_id: projectId, skill_key: skillKey, checkpoint_id: checkpointId, agent_id: agentId, model, week });
      const metric = byKey.get(key) ?? emptySkillCheckpointMetric(projectId, skillKey, checkpointId, agentId, model, week);
      metric.checked_count += item.checked ? 1 : 0;
      metric.hit_count += numberValue(item.finding_count) > 0 ? 1 : 0;
      metric.skip_count += item.skipped ? 1 : 0;
      metric.retry_count += numberValue(item.retry_count);
      metric.retry_hit_count += item.retry_hit ? 1 : 0;
      metric.rejected_count += numberValue(item.rejected_count);
      metric.duplicate_merge_count += numberValue(item.duplicate_merge_count);
      byKey.set(key, metric);
    }
  }
  return [...byKey.values()]
    .map((item) => ({
      ...item,
      hit_rate: item.checked_count ? Number((item.hit_count / item.checked_count).toFixed(4)) : null,
      skip_rate: item.checked_count ? Number((item.skip_count / item.checked_count).toFixed(4)) : null,
      rejected_rate: item.checked_count ? Number((item.rejected_count / item.checked_count).toFixed(4)) : null,
      retry_hit_rate: item.retry_count ? Number((item.retry_hit_count / item.retry_count).toFixed(4)) : null,
      manual_reject_rate: item.manual_accept_count + item.manual_reject_count
        ? Number((item.manual_reject_count / (item.manual_accept_count + item.manual_reject_count)).toFixed(4))
        : null,
      duplicate_rate: item.checked_count ? Number((item.duplicate_merge_count / item.checked_count).toFixed(4)) : null
    }))
    .sort((left, right) => (
      String(left.week).localeCompare(String(right.week))
      || String(left.skill_key).localeCompare(String(right.skill_key))
      || String(left.checkpoint_id).localeCompare(String(right.checkpoint_id))
      || String(left.agent_id).localeCompare(String(right.agent_id))
      || String(left.model).localeCompare(String(right.model))
    ));
}

export class ObservabilityService {
  constructor(private readonly db: Db) {}

  queueSummary(projectId: string) {
    const byStatus = this.db.prepare(`
      SELECT rj.status, COUNT(*) AS count
      FROM review_jobs rj
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      WHERE r.project_id = $1 AND rj.execution_kind = 'production_review'
      GROUP BY rj.status
      ORDER BY rj.status
    `).all(projectId);
    const running = this.db.prepare(`
      SELECT rj.id, rj.status, rj.attempt, rj.locked_at, rj.heartbeat_at, mr.title, mr.number, r.name AS repository_name
      FROM review_jobs rj
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      WHERE r.project_id = $1 AND rj.execution_kind = 'production_review' AND rj.status IN ('fetching', 'pre_scanning', 'reviewing', 'judging')
      ORDER BY rj.locked_at DESC
      LIMIT 20
    `).all(projectId);
    const deadLetters = this.db.prepare(`
      SELECT COUNT(*) AS count
      FROM review_jobs_dead_letter dl
      JOIN review_jobs rj ON rj.id = dl.review_job_id
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      WHERE r.project_id = $1 AND rj.execution_kind = 'production_review'
    `).get(projectId) as { count: number } | undefined;
    const duration = this.db.prepare(`
      SELECT
        COUNT(*) AS completed_runs,
        ROUND(CAST(AVG(EXTRACT(EPOCH FROM NULLIF(rr.completed_at, '')::timestamptz) - EXTRACT(EPOCH FROM NULLIF(rr.started_at, '')::timestamptz)) AS NUMERIC), 2) AS avg_duration_seconds
      FROM review_runs rr
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      WHERE r.project_id = $1 AND rj.execution_kind = 'production_review' AND rr.completed_at IS NOT NULL
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
      WHERE r.project_id = $1 AND rj.execution_kind = 'production_review'
      GROUP BY t.tool_name, t.status
      ORDER BY t.tool_name, t.status
    `).all(projectId);
    const latestRun = this.db.prepare(`
      SELECT rr.id, rr.toolchain_manifest
      FROM review_runs rr
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      WHERE r.project_id = $1 AND rj.execution_kind = 'production_review'
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
      WHERE r.project_id = $1 AND rj.execution_kind = 'production_review'
      GROUP BY rf.agent_id
      ORDER BY finding_count DESC, rf.agent_id
    `).all(projectId) as Array<Record<string, unknown>>;
    const coverageRows = this.db.prepare(`
      SELECT rr.coverage_json
      FROM review_runs rr
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      WHERE r.project_id = $1 AND rj.execution_kind = 'production_review'
        AND rr.coverage_json IS NOT NULL
        AND rr.coverage_json <> '{}'
    `).all(projectId) as Array<{ coverage_json?: string | null }>;
    const coverageByAgent = summarizeBoundRuleCoverageByAgent(coverageRows);
    const byAgent = new Map(items.map((item) => [String(item.agent_id || ""), item]));
    for (const coverage of coverageByAgent) {
      const existing = byAgent.get(coverage.agent_id) ?? { agent_id: coverage.agent_id, finding_count: 0 };
      Object.assign(existing, {
        bound_rule_required_count: coverage.required_count,
        bound_rule_resolved_count: coverage.resolved_count,
        bound_rule_unresolved_count: coverage.unresolved_count,
        bound_rule_resolution_rate: coverage.resolution_rate,
        bound_rule_rejected_count: coverage.rejected_count
      });
      byAgent.set(coverage.agent_id, existing);
    }
    return { project_id: projectId, items: [...byAgent.values()] };
  }

  getReviewQualityMetrics(projectId: string, since?: string | null) {
    const params: unknown[] = [projectId];
    const sinceFilter = since ? "AND rf.created_at >= $2" : "";
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
      WHERE r.project_id = $1 AND rj.execution_kind = 'production_review' ${sinceFilter}
      ORDER BY rf.created_at
    `).all(...params) as Array<{
      id: string;
      severity: string;
      lifecycle_state: string;
      created_at: string;
      feedback_accepted: number;
      feedback_false_positive: number;
    }>;
    const runParams: unknown[] = [projectId];
    const runSinceFilter = since ? "AND COALESCE(rr.completed_at, rr.started_at) >= $2" : "";
    if (since) runParams.push(since);
    const coverageRows = this.db.prepare(`
      SELECT rr.coverage_json
      FROM review_runs rr
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      WHERE r.project_id = $1 AND rj.execution_kind = 'production_review' ${runSinceFilter}
        AND rr.coverage_json IS NOT NULL
        AND rr.coverage_json <> '{}'
      ORDER BY rr.started_at DESC
      LIMIT 200
    `).all(...runParams) as Array<{ coverage_json?: string | null }>;

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
      bound_rule_coverage: summarizeBoundRuleCoverage(coverageRows),
      items
    };
  }

  getSkillCheckpointQualityMetrics(projectId: string, since?: string | null) {
    const runParams: unknown[] = [projectId];
    const runSinceFilter = since ? "AND COALESCE(rr.completed_at, rr.started_at) >= $2" : "";
    if (since) runParams.push(since);
    const runs = this.db.prepare(`
      SELECT rr.id, rr.started_at, rr.coverage_json
      FROM review_runs rr
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      WHERE r.project_id = $1 AND rj.execution_kind = 'production_review' ${runSinceFilter}
        AND rr.coverage_json IS NOT NULL
        AND rr.coverage_json <> '{}'
      ORDER BY rr.started_at DESC
      LIMIT 500
    `).all(...runParams) as Array<{ id: string; started_at?: string | null; coverage_json?: string | null }>;
    const modelRows = this.db.prepare(`
      SELECT rr.id AS run_id, s.agent_id, COALESCE(string_agg(DISTINCT NULLIF(l.model, ''), ','), 'unknown') AS model
      FROM llm_call_records l
      JOIN agent_trace_spans s ON s.id = l.span_id
      JOIN review_runs rr ON rr.id = s.review_run_id
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      WHERE r.project_id = $1 AND rj.execution_kind = 'production_review' ${runSinceFilter}
      GROUP BY rr.id, s.agent_id
    `).all(...runParams) as Array<{ run_id: string; agent_id: string; model: string }>;
    const modelByRunAgent = new Map(modelRows.map((row) => [`${row.run_id}:${row.agent_id}`, row.model || "unknown"]));
    const items = summarizeSkillCheckpointMetrics(projectId, runs, modelByRunAgent);
    const metricByKey = new Map<string, SkillCheckpointMetric>();
    for (const item of items) metricByKey.set(skillCheckpointMetricKey(item), item);
    const checkpointByRunAgentRule = new Map<string, Pick<SkillCheckpointMetric, "project_id" | "skill_key" | "checkpoint_id" | "agent_id" | "model" | "week">>();
    for (const row of runs) {
      const payload = coveragePayload(row);
      const coverageItems = Array.isArray(payload?.items) ? payload.items : [];
      for (const rawItem of coverageItems) {
        if (typeof rawItem !== "object" || !rawItem) continue;
        const item = rawItem as Record<string, unknown>;
        if (String(item.type || "") !== "skill_checkpoint") continue;
        const skillKey = String(item.skill_key || "skill_bundle").trim();
        const checkpointId = String(item.checkpoint_id || item.rule_id || "").trim();
        const agentId = String(item.agent_id || "").trim();
        if (!skillKey || !checkpointId || !agentId) continue;
        const model = modelByRunAgent.get(`${row.id}:${agentId}`) || "unknown";
        const week = isoWeekKey(row.started_at);
        checkpointByRunAgentRule.set(`${row.id}\u0001${agentId}\u0001${checkpointId}`, {
          project_id: projectId,
          skill_key: skillKey,
          checkpoint_id: checkpointId,
          agent_id: agentId,
          model,
          week
        });
      }
    }
    const feedbackParams: unknown[] = [projectId];
    const feedbackSinceFilter = since ? "AND rf.created_at >= $2" : "";
    if (since) feedbackParams.push(since);
    const feedbackRows = this.db.prepare(`
      SELECT
        rr.id AS run_id,
        rr.started_at,
        rf.agent_id,
        rf.covered_rules_json,
        rf.lifecycle_state,
        COALESCE(fb.accepted, 0) AS feedback_accepted,
        COALESCE(fb.false_positive, 0) AS feedback_false_positive,
        COALESCE(fb.dismissed, 0) AS feedback_dismissed
      FROM review_findings rf
      JOIN review_runs rr ON rr.id = rf.review_run_id
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      JOIN merge_requests mr ON mr.id = rj.merge_request_id
      JOIN repositories r ON r.id = mr.repository_id
      LEFT JOIN (
        SELECT
          finding_id,
          MAX(CASE WHEN feedback_type = 'accepted' THEN 1 ELSE 0 END) AS accepted,
          MAX(CASE WHEN feedback_type = 'false_positive' THEN 1 ELSE 0 END) AS false_positive,
          MAX(CASE WHEN feedback_type = 'dismissed' THEN 1 ELSE 0 END) AS dismissed
        FROM user_feedback
        GROUP BY finding_id
      ) fb ON fb.finding_id = rf.id
      WHERE r.project_id = $1 AND rj.execution_kind = 'production_review' ${feedbackSinceFilter}
    `).all(...feedbackParams) as Array<{
      run_id: string;
      started_at?: string | null;
      agent_id: string;
      covered_rules_json?: string | null;
      lifecycle_state: string;
      feedback_accepted: number;
      feedback_false_positive: number;
      feedback_dismissed: number;
    }>;
    for (const row of feedbackRows) {
      const rules = parseJson(row.covered_rules_json);
      const coveredRules = Array.isArray(rules) ? rules.map((rule) => String(rule || "").trim()).filter(Boolean) : [];
      const rejected = ["false_positive", "dismissed"].includes(String(row.lifecycle_state || "")) || Number(row.feedback_false_positive || 0) > 0 || Number(row.feedback_dismissed || 0) > 0;
      const accepted = String(row.lifecycle_state || "") === "accepted" || Number(row.feedback_accepted || 0) > 0;
      if (!rejected && !accepted) continue;
      for (const ruleId of coveredRules) {
        const dimensions = checkpointByRunAgentRule.get(`${row.run_id}\u0001${row.agent_id}\u0001${ruleId}`);
        if (!dimensions) continue;
        const key = skillCheckpointMetricKey(dimensions);
        const metric = metricByKey.get(key) ?? emptySkillCheckpointMetric(
          dimensions.project_id,
          dimensions.skill_key,
          dimensions.checkpoint_id,
          dimensions.agent_id,
          dimensions.model,
          dimensions.week || isoWeekKey(row.started_at)
        );
        if (rejected) metric.manual_reject_count += 1;
        else if (accepted) metric.manual_accept_count += 1;
        metricByKey.set(key, metric);
      }
    }
    const finalItems = [...metricByKey.values()].map((item) => ({
      ...item,
      hit_rate: item.checked_count ? Number((item.hit_count / item.checked_count).toFixed(4)) : null,
      skip_rate: item.checked_count ? Number((item.skip_count / item.checked_count).toFixed(4)) : null,
      rejected_rate: item.checked_count ? Number((item.rejected_count / item.checked_count).toFixed(4)) : null,
      retry_hit_rate: item.retry_count ? Number((item.retry_hit_count / item.retry_count).toFixed(4)) : null,
      manual_reject_rate: item.manual_accept_count + item.manual_reject_count
        ? Number((item.manual_reject_count / (item.manual_accept_count + item.manual_reject_count)).toFixed(4))
        : null,
      duplicate_rate: item.checked_count ? Number((item.duplicate_merge_count / item.checked_count).toFixed(4)) : null
    })).sort((left, right) => (
      String(left.week).localeCompare(String(right.week))
      || String(left.skill_key).localeCompare(String(right.skill_key))
      || String(left.checkpoint_id).localeCompare(String(right.checkpoint_id))
      || String(left.agent_id).localeCompare(String(right.agent_id))
      || String(left.model).localeCompare(String(right.model))
    ));
    const totals = finalItems.reduce(
      (acc, item) => {
        acc.checked_count += item.checked_count;
        acc.hit_count += item.hit_count;
        acc.skip_count += item.skip_count;
        acc.retry_count += item.retry_count;
        acc.retry_hit_count += item.retry_hit_count;
        acc.rejected_count += item.rejected_count;
        acc.manual_accept_count += item.manual_accept_count;
        acc.manual_reject_count += item.manual_reject_count;
        acc.duplicate_merge_count += item.duplicate_merge_count;
        return acc;
      },
      {
        checked_count: 0,
        hit_count: 0,
        skip_count: 0,
        retry_count: 0,
        retry_hit_count: 0,
        rejected_count: 0,
        manual_accept_count: 0,
        manual_reject_count: 0,
        duplicate_merge_count: 0
      }
    );
    return {
      project_id: projectId,
      since: since || null,
      dimensions: ["project_id", "skill_key", "checkpoint_id", "agent_id", "model", "week"],
      totals: {
        ...totals,
        hit_rate: totals.checked_count ? Number((totals.hit_count / totals.checked_count).toFixed(4)) : null,
        rejected_rate: totals.checked_count ? Number((totals.rejected_count / totals.checked_count).toFixed(4)) : null,
        manual_reject_rate: totals.manual_accept_count + totals.manual_reject_count
          ? Number((totals.manual_reject_count / (totals.manual_accept_count + totals.manual_reject_count)).toFixed(4))
          : null,
        retry_hit_rate: totals.retry_count ? Number((totals.retry_hit_count / totals.retry_count).toFixed(4)) : null,
        duplicate_rate: totals.checked_count ? Number((totals.duplicate_merge_count / totals.checked_count).toFixed(4)) : null
      },
      items: finalItems
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
