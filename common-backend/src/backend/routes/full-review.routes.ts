import { badRequest, id, notFound, route, type Route } from "../http.js";
import type { BackendRouteContext } from "./context.js";

const ACTIVE_JOB_STATES = new Set(["queued", "running"]);
const MUTABLE_FINDING_STATES = new Set(["pending", "accepted", "dismissed", "false_positive"]);

interface FullReviewJobRow {
  id: string;
  project_id: string;
  repository_id: string | null;
  commit_sha: string;
  scope_json: string;
  status: string;
  requested_by: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

interface FullReviewFindingProjectRow {
  id: string;
  project_id: string;
}

export function createFullReviewRoutes(ctx: BackendRouteContext): Route[] {
  const {
    all,
    get,
    db,
    currentUserId,
    ensureProjectRole,
    ensureProjectWrite,
    auditLog,
    repositoryRepository
  } = ctx;

  function parseObject(value: unknown, fallback: Record<string, unknown> = {}) {
    return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : fallback;
  }

  function normalizeJob(row: FullReviewJobRow) {
    return {
      ...row,
      scope: JSON.parse(row.scope_json || "{}"),
      scope_json: undefined
    };
  }

  function parseJson(value: string | null | undefined, fallback: Record<string, unknown> = {}) {
    try {
      return JSON.parse(value || "{}");
    } catch {
      return fallback;
    }
  }

  function findJobWithAccess(jobId: string, userId: string, minRole: string) {
    const job = get<FullReviewJobRow>("SELECT * FROM full_review_jobs WHERE id = ?", [jobId]);
    if (!job) return { result: notFound() };
    const denied = ensureProjectRole(job.project_id, userId, minRole);
    if (denied) return { result: denied };
    return { job };
  }

  const routes: Route[] = [
    route("GET", "/api/full-review/projects/:projectId/jobs", ({ params, req, url }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "observer");
      if (denied) return denied;
      const limit = Math.min(100, Math.max(1, Number(url.searchParams.get("limit") ?? 50)));
      const status = url.searchParams.get("status");
      const rows = status
        ? all<FullReviewJobRow>(
            "SELECT * FROM full_review_jobs WHERE project_id = ? AND status = ? ORDER BY created_at DESC LIMIT ?",
            [params.projectId, status, limit]
          )
        : all<FullReviewJobRow>(
            "SELECT * FROM full_review_jobs WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
            [params.projectId, limit]
          );
      return { project_id: params.projectId, items: rows.map(normalizeJob) };
    }),

    route("POST", "/api/full-review/projects/:projectId/jobs", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      const input = parseObject(body);
      const repositoryId = input.repository_id ? String(input.repository_id) : null;
      if (repositoryId) {
        const repo = repositoryRepository.findById(repositoryId) as { id: string; project_id: string } | undefined;
        if (!repo || repo.project_id !== params.projectId) return badRequest("repository_id must belong to project");
      }
      const commitSha = String(input.commit_sha ?? "").trim();
      const scope = parseObject(input.scope, { mode: repositoryId ? "repository" : "project" });
      const jobId = id("full_job");
      db.prepare(`
        INSERT INTO full_review_jobs (
          id, project_id, repository_id, commit_sha, scope_json, status, requested_by
        )
        VALUES (?, ?, ?, ?, ?, 'queued', ?)
      `).run(jobId, params.projectId, repositoryId, commitSha, JSON.stringify(scope), actorId);
      auditLog({
        userId: actorId,
        projectId: params.projectId,
        action: "full_review.enqueue",
        resourceType: "full_review_job",
        resourceId: jobId,
        summary: repositoryId ? `queued repository ${repositoryId}` : "queued project full review",
        metadata: { repository_id: repositoryId, commit_sha: commitSha || null, scope }
      });
      const job = get<FullReviewJobRow>("SELECT * FROM full_review_jobs WHERE id = ?", [jobId]);
      return job ? normalizeJob(job) : notFound();
    }),

    route("GET", "/api/full-review/jobs/:jobId", ({ params, req }) => {
      const actorId = currentUserId(req);
      const { job, result } = findJobWithAccess(params.jobId, actorId, "observer");
      if (!job) return result;
      const snapshots = all("SELECT * FROM full_review_snapshots WHERE job_id = ? ORDER BY created_at DESC", [params.jobId]);
      return { ...normalizeJob(job), snapshots };
    }),

    route("POST", "/api/full-review/jobs/:jobId/cancel", ({ params, req }) => {
      const actorId = currentUserId(req);
      const { job, result } = findJobWithAccess(params.jobId, actorId, "reviewer");
      if (!job) return result;
      if (!ACTIVE_JOB_STATES.has(job.status)) {
        return { ...normalizeJob(job), cancelled: false, reason: `job is ${job.status}` };
      }
      db.prepare(`
        UPDATE full_review_jobs
        SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP, completed_at = CURRENT_TIMESTAMP
        WHERE id = ?
      `).run(params.jobId);
      auditLog({
        userId: actorId,
        projectId: job.project_id,
        action: "full_review.cancel",
        resourceType: "full_review_job",
        resourceId: params.jobId,
        summary: "cancelled full review job"
      });
      const updated = get<FullReviewJobRow>("SELECT * FROM full_review_jobs WHERE id = ?", [params.jobId]);
      return updated ? { ...normalizeJob(updated), cancelled: true } : notFound();
    }),

    route("GET", "/api/full-review/jobs/:jobId/trace", ({ params, req }) => {
      const actorId = currentUserId(req);
      const { job, result } = findJobWithAccess(params.jobId, actorId, "observer");
      if (!job) return result;
      return {
        job_id: params.jobId,
        items: all("SELECT * FROM audit_logs WHERE resource_type = 'full_review_job' AND resource_id = ? ORDER BY created_at", [params.jobId])
      };
    }),

    route("GET", "/api/full-review/jobs/:jobId/session-logs", ({ params, req }) => {
      const actorId = currentUserId(req);
      const { job, result } = findJobWithAccess(params.jobId, actorId, "observer");
      if (!job) return result;
      const logs = all<Record<string, any>>("SELECT * FROM audit_logs WHERE resource_type = 'full_review_job' AND resource_id = ? ORDER BY created_at", [params.jobId]);
      const toolCalls = logs
        .filter((item) => item.action === "full_review.tool_call")
        .map((item) => ({ ...item, metadata: parseJson(item.metadata_json) }));
      const artifacts = logs
        .filter((item) => item.action === "full_review.artifact")
        .map((item) => ({ ...item, metadata: parseJson(item.metadata_json) }));
      return {
        job_id: params.jobId,
        events: logs,
        spans: [],
        messages: [],
        tool_calls: toolCalls,
        llm_calls: [],
        mcp_calls: [],
        artifacts
      };
    }),

    route("GET", "/api/full-review/repositories/:repositoryId/snapshots", ({ params, req }) => {
      const actorId = currentUserId(req);
      const repo = repositoryRepository.findById(params.repositoryId) as { id: string; project_id: string } | undefined;
      if (!repo) return notFound();
      const denied = ensureProjectRole(repo.project_id, actorId, "observer");
      if (denied) return denied;
      return {
        repository_id: params.repositoryId,
        items: all("SELECT * FROM full_review_snapshots WHERE repository_id = ? ORDER BY created_at DESC", [params.repositoryId])
      };
    }),

    route("GET", "/api/full-review/snapshots/:snapshotId/findings", ({ params, req }) => {
      const actorId = currentUserId(req);
      const snapshot = get<{ id: string; project_id: string }>(`
        SELECT s.id, j.project_id
        FROM full_review_snapshots s
        JOIN full_review_jobs j ON j.id = s.job_id
        WHERE s.id = ?
      `, [params.snapshotId]);
      if (!snapshot) return notFound();
      const denied = ensureProjectRole(snapshot.project_id, actorId, "observer");
      if (denied) return denied;
      return {
        snapshot_id: params.snapshotId,
        items: all("SELECT * FROM full_review_findings WHERE snapshot_id = ? ORDER BY severity DESC, confidence DESC, created_at", [params.snapshotId])
      };
    }),

    route("PATCH", "/api/full-review/findings/:findingId", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const input = parseObject(body);
      const finding = get<FullReviewFindingProjectRow>(`
        SELECT f.id, j.project_id
        FROM full_review_findings f
        JOIN full_review_snapshots s ON s.id = f.snapshot_id
        JOIN full_review_jobs j ON j.id = s.job_id
        WHERE f.id = ?
      `, [params.findingId]);
      if (!finding) return notFound();
      const denied = ensureProjectRole(finding.project_id, actorId, "developer");
      if (denied) return denied;
      if (typeof input.selected === "boolean") {
        db.prepare("UPDATE full_review_findings SET selected = ? WHERE id = ?").run(input.selected ? 1 : 0, params.findingId);
        auditLog({
          userId: actorId,
          projectId: finding.project_id,
          action: "full_review.finding.select",
          resourceType: "full_review_finding",
          resourceId: params.findingId,
          summary: `selected=${input.selected}`
        });
      }
      if (typeof input.lifecycle_state === "string") {
        const lifecycleState = input.lifecycle_state.trim();
        if (!MUTABLE_FINDING_STATES.has(lifecycleState)) return badRequest("unsupported lifecycle_state");
        db.prepare("UPDATE full_review_findings SET lifecycle_state = ? WHERE id = ?").run(lifecycleState, params.findingId);
        auditLog({
          userId: actorId,
          projectId: finding.project_id,
          action: "full_review.finding.lifecycle",
          resourceType: "full_review_finding",
          resourceId: params.findingId,
          summary: lifecycleState
        });
      }
      return get("SELECT * FROM full_review_findings WHERE id = ?", [params.findingId]);
    })
  ];
  return routes;
}
