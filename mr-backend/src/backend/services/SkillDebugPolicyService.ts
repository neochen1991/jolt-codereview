import type { Db } from "../db.js";
import type { AppConfig } from "../types.js";

export type SkillDebugPolicy = Required<NonNullable<AppConfig["skill_debug_policy"]>>;

export class SkillDebugPolicyService {
  constructor(private readonly db: Db) {}

  resolve(config: AppConfig): SkillDebugPolicy {
    const value = config.skill_debug_policy || {};
    return {
      project_max_concurrency: Math.max(1, Number(value.project_max_concurrency ?? 2)),
      user_max_concurrency: Math.max(1, Number(value.user_max_concurrency ?? 1)),
      daily_session_limit: Math.max(1, Number(value.daily_session_limit ?? 20)),
      daily_token_limit: Math.max(1, Number(value.daily_token_limit ?? 1_000_000)),
      max_duration_seconds: Math.max(60, Number(value.max_duration_seconds ?? 1800)),
      retention_days: Math.max(1, Number(value.retention_days ?? 14))
      ,debug_job_max_concurrency: Math.max(1, Number(value.debug_job_max_concurrency ?? 1))
    };
  }

  checkCreate(projectId: string, userId: string, config: AppConfig) {
    const policy = this.resolve(config);
    const activeStatuses = "('queued','running')";
    const projectActive = this.db.prepare(`SELECT COUNT(*) AS count FROM skill_debug_sessions WHERE project_id = $1 AND status IN ${activeStatuses}`)
      .get(projectId) as { count?: number } | undefined;
    if (Number(projectActive?.count || 0) >= policy.project_max_concurrency) {
      return { statusCode: 429, error: "skill_debug_project_concurrency_exceeded", message: `项目同时最多运行 ${policy.project_max_concurrency} 个 Skill 调试会话` };
    }
    const userActive = this.db.prepare(`SELECT COUNT(*) AS count FROM skill_debug_sessions WHERE project_id = $1 AND requested_by = $2 AND status IN ${activeStatuses}`)
      .get(projectId, userId) as { count?: number } | undefined;
    if (Number(userActive?.count || 0) >= policy.user_max_concurrency) {
      return { statusCode: 429, error: "skill_debug_user_concurrency_exceeded", message: `每位用户同时最多运行 ${policy.user_max_concurrency} 个 Skill 调试会话` };
    }
    const daily = this.db.prepare(`
      SELECT COUNT(*) AS count FROM skill_debug_sessions
      WHERE project_id = $1 AND requested_by = $2 AND created_at::timestamptz >= CURRENT_TIMESTAMP - INTERVAL '1 day'
    `).get(projectId, userId) as { count?: number } | undefined;
    if (Number(daily?.count || 0) >= policy.daily_session_limit) {
      return { statusCode: 429, error: "skill_debug_daily_session_limit_exceeded", message: `每天最多创建 ${policy.daily_session_limit} 个 Skill 调试会话` };
    }
    const tokens = this.db.prepare(`
      SELECT COALESCE(SUM(l.input_tokens + l.output_tokens), 0) AS total
      FROM llm_call_records l
      JOIN agent_trace_spans ats ON ats.id = l.span_id
      JOIN review_runs rr ON rr.id = ats.review_run_id
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      JOIN skill_debug_sessions s ON s.id = rj.debug_session_id
      WHERE s.project_id = $1 AND s.requested_by = $2
        AND s.created_at::timestamptz >= CURRENT_TIMESTAMP - INTERVAL '1 day'
    `).get(projectId, userId) as { total?: number } | undefined;
    if (Number(tokens?.total || 0) >= policy.daily_token_limit) {
      return { statusCode: 429, error: "skill_debug_daily_token_limit_exceeded", message: `每天 Skill 调试 Token 上限为 ${policy.daily_token_limit}` };
    }
    return null;
  }
}
