import { randomBytes } from "node:crypto";
import { badRequest, id, notFound, route, sha1, type Route } from "../http.js";
import type { FindingRow } from "../types.js";
import type { BackendRouteContext } from "./context.js";

export function createHealthRoutes(ctx: BackendRouteContext): Route[] {
  const {
    all,
    get,
    db,
    config,
    runWorkerOnce,
    repoConfig,
    riskScore,
    verifyGitHubSignature,
    verifyCodeHubSignature,
    normalizeCodeHubWebhookPayload,
    codehubRepoMatches,
    bearerToken,
    currentUserId,
    ensureProjectRole,
    ensureProjectWrite,
    auditLog,
    syncProject,
    publishFindings,
    projectRepository,
    repositoryRepository,
    mergeRequestRepository,
    reviewJobRepository,
    agentRepository,
    ruleDocumentRepository,
    auditRepository
  } = ctx;
  function percentile(values: number[], p: number) {
    if (!values.length) return null;
    const sorted = [...values].sort((a, b) => a - b);
    const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
    return sorted[index];
  }

  function healthSli() {
    const runs = all<Record<string, unknown>>(
      `
      SELECT
        rr.effort_level,
        rr.status,
        rr.started_at,
        rr.completed_at,
        rj.created_at AS job_created_at,
        CASE
          WHEN rr.completed_at IS NULL THEN NULL
          ELSE strftime('%s', rr.completed_at) - strftime('%s', rr.started_at)
        END AS run_seconds,
        strftime('%s', rr.started_at) - strftime('%s', rj.created_at) AS queue_wait_seconds
      FROM review_runs rr
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      WHERE rr.started_at >= datetime('now', '-24 hours')
      `,
      []
    );
    const jobs = all<Record<string, unknown>>(
      "SELECT status FROM review_jobs WHERE created_at >= datetime('now', '-24 hours')",
      []
    );
    const feedback = get<Record<string, unknown>>(
      `
      SELECT
        COUNT(*) AS total,
        SUM(CASE WHEN feedback_type = 'false_positive' THEN 1 ELSE 0 END) AS false_positive
      FROM user_feedback
      WHERE created_at >= datetime('now', '-30 days')
      `,
      []
    ) ?? { total: 0, false_positive: 0 };
    const durationsByEffort: Record<string, number[]> = { light: [], fast: [], standard: [], deep: [], trivial: [] };
    const queueWaits: number[] = [];
    for (const run of runs) {
      const effort = String(run.effort_level || "standard");
      const duration = Number(run.run_seconds);
      if (Number.isFinite(duration) && duration >= 0) {
        (durationsByEffort[effort] ||= []).push(duration);
      }
      const queueWait = Number(run.queue_wait_seconds);
      if (Number.isFinite(queueWait) && queueWait >= 0) queueWaits.push(queueWait);
    }
    const completed = runs.filter((item) => ["waiting_confirmation", "no_issue", "submitted"].includes(String(item.status))).length;
    const failed = jobs.filter((item) => ["failed", "dead_letter"].includes(String(item.status))).length;
    const availability = jobs.length ? Number(((jobs.length - failed) / jobs.length).toFixed(4)) : null;
    const falsePositiveRate = Number(feedback.total || 0)
      ? Number((Number(feedback.false_positive || 0) / Number(feedback.total || 0)).toFixed(4))
      : null;
    const p95 = {
      light_seconds: percentile([...(durationsByEffort.light || []), ...(durationsByEffort.fast || [])], 95),
      standard_seconds: percentile(durationsByEffort.standard || [], 95),
      deep_seconds: percentile(durationsByEffort.deep || [], 95),
      queue_wait_seconds: percentile(queueWaits, 95),
    };
    return {
      window: {
        runtime: "24h",
        feedback: "30d",
      },
      slo_targets: {
        availability_monthly: 0.995,
        light_p95_seconds: 90,
        standard_p95_seconds: 300,
        deep_p95_seconds: 900,
        queue_wait_p95_seconds: 30,
        false_positive_rate_max: 0.25,
        gold_set_recall_min: 0.75,
      },
      current: {
        jobs_24h: jobs.length,
        runs_24h: runs.length,
        completed_runs_24h: completed,
        failed_jobs_24h: failed,
        availability_proxy: availability,
        p95,
        false_positive_rate: falsePositiveRate,
      },
      status: {
        availability: availability === null || availability >= 0.995 ? "ok" : "breached",
        light_latency: p95.light_seconds === null || p95.light_seconds <= 90 ? "ok" : "breached",
        standard_latency: p95.standard_seconds === null || p95.standard_seconds <= 300 ? "ok" : "breached",
        deep_latency: p95.deep_seconds === null || p95.deep_seconds <= 900 ? "ok" : "breached",
        queue_wait: p95.queue_wait_seconds === null || p95.queue_wait_seconds <= 30 ? "ok" : "breached",
        false_positive_rate: falsePositiveRate === null || falsePositiveRate <= 0.25 ? "ok" : "breached",
      },
      docs: "docs/nfr-and-slo.md",
    };
  }

  const routes: Route[] = [
    route("GET", "/api/health", () => ({ ok: true, service: "jolt-codereview-api", sli: healthSli() })),
  ];
  return routes;
}
