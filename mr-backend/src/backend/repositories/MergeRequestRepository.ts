import type { Db } from "../db.js";
import type { MergeRequestRow } from "../types.js";

export class MergeRequestRepository {
  constructor(private readonly db: Db) {}

  findById(id: string) {
    return this.db.prepare("SELECT * FROM merge_requests WHERE id = $1").get(id) as MergeRequestRow | undefined;
  }

  findByRepositoryAndExternalId(repositoryId: string, externalMrId: string) {
    return this.db.prepare("SELECT * FROM merge_requests WHERE repository_id = $1 AND external_mr_id = $2").get(repositoryId, externalMrId) as MergeRequestRow | undefined;
  }

  findDetailById(id: string) {
    return this.db.prepare(`
      SELECT mr.*, r.name AS repository_name, r.provider, r.external_repo_id
      FROM merge_requests mr
      JOIN repositories r ON r.id = mr.repository_id
      WHERE mr.id = $1
    `).get(id);
  }

  listByProject(projectId: string, status: string | null) {
    const baseSql = `
      SELECT
        mr.*,
        r.name AS repository_name,
        r.provider,
        (
          SELECT COUNT(*)
          FROM review_findings rf
          WHERE rf.review_run_id = (
            SELECT rr_latest.id
            FROM review_runs rr_latest
            JOIN review_jobs rj_latest ON rj_latest.id = rr_latest.review_job_id
            WHERE rj_latest.merge_request_id = mr.id
            ORDER BY rr_latest.started_at DESC
            LIMIT 1
          )
        ) AS finding_count,
        (
          SELECT rr.status FROM review_runs rr
          JOIN review_jobs rj ON rj.id = rr.review_job_id
          WHERE rj.merge_request_id = mr.id
          ORDER BY rr.started_at DESC
          LIMIT 1
        ) AS latest_run_status,
        (
          SELECT rr.started_at FROM review_runs rr
          JOIN review_jobs rj ON rj.id = rr.review_job_id
          WHERE rj.merge_request_id = mr.id
          ORDER BY rr.started_at DESC
          LIMIT 1
        ) AS review_started_at,
        (
          SELECT rj.status FROM review_jobs rj
          WHERE rj.merge_request_id = mr.id
          ORDER BY rj.updated_at DESC, rj.created_at DESC
          LIMIT 1
        ) AS latest_job_status
      FROM merge_requests mr
      JOIN repositories r ON r.id = mr.repository_id
      WHERE r.project_id = $1
        AND r.status = 'active'
    `;
    const orderSql = `
      ORDER BY mr.risk_score DESC, mr.updated_at DESC
    `;
    if (status === null) {
      return this.db.prepare(`${baseSql}${orderSql}`).all(projectId);
    }
    return this.db.prepare(`${baseSql} AND mr.review_status = $2 ${orderSql}`).all(projectId, status);
  }

  listRemoteStatusCandidates(projectId: string) {
    return this.db.prepare(`
      SELECT mr.*, r.project_id, r.provider, r.external_repo_id, r.name AS repository_name, r.provider_config_json
      FROM merge_requests mr
      JOIN repositories r ON r.id = mr.repository_id
      WHERE r.project_id = $1
        AND r.status = 'active'
        AND mr.review_status IN ('queued', 'paused', 'waiting_confirmation', 'no_issue', 'too_large')
      ORDER BY mr.updated_at DESC
      LIMIT 200
    `).all(projectId);
  }

  upsert(input: {
    id: string;
    repositoryId: string;
    externalMrId: string;
    number: number;
    title: string;
    author: string;
    sourceBranch: string;
    targetBranch: string;
    riskScore: number;
    latestHeadSha: string;
    htmlUrl: string;
    metadata: Record<string, unknown>;
  }) {
    this.db.prepare(`
      INSERT INTO merge_requests (
        id, repository_id, external_mr_id, number, title, author, source_branch, target_branch,
        review_status, risk_score, latest_head_sha, html_url, metadata_json, updated_at
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, CURRENT_TIMESTAMP)
      ON CONFLICT(repository_id, external_mr_id) DO UPDATE SET
        title = excluded.title,
        author = excluded.author,
        source_branch = excluded.source_branch,
        target_branch = excluded.target_branch,
        risk_score = excluded.risk_score,
        latest_head_sha = excluded.latest_head_sha,
        html_url = excluded.html_url,
        metadata_json = excluded.metadata_json,
        review_status = CASE
          WHEN merge_requests.latest_head_sha != excluded.latest_head_sha THEN 'queued'
          ELSE merge_requests.review_status
        END,
        updated_at = CURRENT_TIMESTAMP
    `).run(
      input.id,
      input.repositoryId,
      input.externalMrId,
      input.number,
      input.title,
      input.author,
      input.sourceBranch,
      input.targetBranch,
      "queued",
      input.riskScore,
      input.latestHeadSha,
      input.htmlUrl,
      JSON.stringify(input.metadata)
    );
  }

  updateReviewStatus(id: string, status: string) {
    this.db.prepare("UPDATE merge_requests SET review_status = $1 WHERE id = $2").run(status, id);
  }

  deleteById(id: string) {
    const mr = this.findById(id);
    if (!mr) {
      return {
        ok: false,
        deleted_merge_requests: 0,
        deleted_jobs: 0,
        deleted_runs: 0,
        deleted_findings: 0
      };
    }

    const jobIds = this.db.prepare("SELECT id FROM review_jobs WHERE merge_request_id = $1").all(id).map((row: any) => String(row.id));
    const runIds = this.db.prepare(`
      SELECT rr.id
      FROM review_runs rr
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      WHERE rj.merge_request_id = $1
    `).all(id).map((row: any) => String(row.id));
    const findingIds = this.db.prepare(`
      SELECT rf.id
      FROM review_findings rf
      JOIN review_runs rr ON rr.id = rf.review_run_id
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      WHERE rj.merge_request_id = $1
    `).all(id).map((row: any) => String(row.id));
    const spanIds = this.db.prepare(`
      SELECT s.id
      FROM agent_trace_spans s
      JOIN review_runs rr ON rr.id = s.review_run_id
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      WHERE rj.merge_request_id = $1
    `).all(id).map((row: any) => String(row.id));

    let changes = 0;
    const run = (sql: string, value: string) => {
      changes += Number(this.db.prepare(sql).run(value).changes);
    };
    const runEach = (sql: string, values: string[]) => {
      for (const value of values) run(sql, value);
    };

    this.db.exec("BEGIN");
    try {
      runEach("DELETE FROM vcs_publish_records WHERE finding_id = $1", findingIds);
      runEach("DELETE FROM user_feedback WHERE finding_id = $1", findingIds);
      runEach("DELETE FROM evaluation_gold_set WHERE finding_id = $1", findingIds);
      run("DELETE FROM mr_finding_history WHERE merge_request_id = $1", id);
      runEach("DELETE FROM review_findings WHERE id = $1", findingIds);

      runEach("DELETE FROM agent_trace_events WHERE span_id = $1", spanIds);
      runEach("DELETE FROM agent_messages WHERE span_id = $1", spanIds);
      runEach("DELETE FROM llm_call_records WHERE span_id = $1", spanIds);
      runEach("DELETE FROM tool_call_records WHERE span_id = $1", spanIds);
      runEach("DELETE FROM mcp_call_records WHERE span_id = $1", spanIds);
      runEach("DELETE FROM agent_trace_spans WHERE id = $1", spanIds);

      runEach("DELETE FROM tool_observations WHERE review_run_id = $1", runIds);
      runEach("DELETE FROM review_artifacts WHERE review_run_id = $1", runIds);
      runEach("DELETE FROM code_index_snapshots WHERE review_run_id = $1", runIds);
      runEach("DELETE FROM review_runs WHERE id = $1", runIds);

      runEach("DELETE FROM review_jobs_dead_letter WHERE review_job_id = $1", jobIds);
      runEach("DELETE FROM review_jobs WHERE id = $1", jobIds);
      run("DELETE FROM external_review_reports WHERE merge_request_id = $1", id);
      const deletedMr = Number(this.db.prepare("DELETE FROM merge_requests WHERE id = $1").run(id).changes);
      changes += deletedMr;

      this.db.exec("COMMIT");
      return {
        ok: deletedMr > 0,
        deleted_merge_requests: deletedMr,
        deleted_jobs: jobIds.length,
        deleted_runs: runIds.length,
        deleted_findings: findingIds.length,
        deleted_related_rows: changes
      };
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }
}
