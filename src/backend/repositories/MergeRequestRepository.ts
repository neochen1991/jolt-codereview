import type { Db } from "../db.js";
import type { MergeRequestRow } from "../types.js";

export class MergeRequestRepository {
  constructor(private readonly db: Db) {}

  findById(id: string) {
    return this.db.prepare("SELECT * FROM merge_requests WHERE id = ?").get(id) as MergeRequestRow | undefined;
  }

  findByRepositoryAndExternalId(repositoryId: string, externalMrId: string) {
    return this.db.prepare("SELECT * FROM merge_requests WHERE repository_id = ? AND external_mr_id = ?").get(repositoryId, externalMrId) as MergeRequestRow | undefined;
  }

  findDetailById(id: string) {
    return this.db.prepare(`
      SELECT mr.*, r.name AS repository_name, r.provider, r.external_repo_id
      FROM merge_requests mr
      JOIN repositories r ON r.id = mr.repository_id
      WHERE mr.id = ?
    `).get(id);
  }

  listByProject(projectId: string, status: string | null) {
    return this.db.prepare(`
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
          SELECT rj.status FROM review_jobs rj
          WHERE rj.merge_request_id = mr.id
          ORDER BY rj.updated_at DESC, rj.created_at DESC
          LIMIT 1
        ) AS latest_job_status
      FROM merge_requests mr
      JOIN repositories r ON r.id = mr.repository_id
      WHERE r.project_id = ?
        AND r.status = 'active'
        AND (? IS NULL OR mr.review_status = ?)
      ORDER BY mr.risk_score DESC, mr.updated_at DESC
    `).all(projectId, status, status);
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
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
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
    this.db.prepare("UPDATE merge_requests SET review_status = ? WHERE id = ?").run(status, id);
  }
}
