import { randomBytes } from "node:crypto";
import { badRequest, id, notFound, route, sha1, type Route } from "../http.js";
import { formatMrReviewMarkdown, markdownFilename } from "../reviewMarkdown.js";
import type { FindingRow } from "../types.js";
import type { BackendRouteContext } from "./context.js";

export function createReviewRoutes(ctx: BackendRouteContext): Route[] {
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
    auditRepository,
    reviewQueueService,
    feedbackLearningService
  } = ctx;
  function compareRunsForMr(mrId: string) {
    const runs = all<{ id: string; review_job_id: string; started_at: string }>(`
      SELECT rr.id, rr.review_job_id, rr.started_at
      FROM review_runs rr
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      WHERE rj.merge_request_id = ?
      ORDER BY rr.started_at DESC
      LIMIT 2
    `, [mrId]);
    if (runs.length < 2) return { base_run: runs[1] ?? null, head_run: runs[0] ?? null, added: [], resolved: [], retained: [] };
    const [headRun, baseRun] = runs;
    const head = all<FindingRow>("SELECT * FROM review_findings WHERE review_run_id = ?", [headRun.id]);
    const base = all<FindingRow>("SELECT * FROM review_findings WHERE review_run_id = ?", [baseRun.id]);
    const headByHash = new Map(head.map((finding) => [finding.dedupe_hash, finding]));
    const baseByHash = new Map(base.map((finding) => [finding.dedupe_hash, finding]));
    return {
      base_run: baseRun,
      head_run: headRun,
      added: head.filter((finding) => !baseByHash.has(finding.dedupe_hash)),
      resolved: base.filter((finding) => !headByHash.has(finding.dedupe_hash)),
      retained: head.filter((finding) => baseByHash.has(finding.dedupe_hash))
    };
  }

  function countByKind(items: Array<{ kind: string }>): Record<string, number> {
    return items.reduce<Record<string, number>>((acc, item) => {
      acc[item.kind] = (acc[item.kind] ?? 0) + 1;
      return acc;
    }, {});
  }

  function unifiedReviewLogs(mrId: string, runId?: string | null) {
    const runs = all<Record<string, any>>(`
      SELECT rr.* FROM review_runs rr
      JOIN review_jobs rj ON rj.id = rr.review_job_id
      WHERE rj.merge_request_id = ?
      ORDER BY rr.started_at DESC
    `, [mrId]);
    const selectedRun = runId ? runs.find((run) => run.id === runId) : runs[0];
    const jobs = reviewJobRepository.listByMergeRequest(mrId) as Array<Record<string, any>>;
    const items: Array<Record<string, any> & { kind: string; timestamp: string }> = [];

    for (const job of jobs) {
      items.push({
        kind: "review_job",
        id: job.id,
        timestamp: String(job.created_at ?? ""),
        status: job.status,
        summary: `检视任务创建：${job.status}`,
        merge_request_id: job.merge_request_id,
        head_sha: job.head_sha,
        effort_level: job.requested_effort_level,
        priority: job.priority,
        attempt: job.attempt
      });
      if (job.updated_at) {
        items.push({
          kind: "review_job_status",
          id: job.id,
          timestamp: String(job.updated_at),
          status: job.status,
          summary: `检视任务状态更新：${job.status}`,
          locked_by: job.locked_by,
          heartbeat_at: job.heartbeat_at,
          error_message: job.error_message
        });
      }
    }

    if (selectedRun) {
      items.push({
        kind: "review_run",
        id: selectedRun.id,
        timestamp: String(selectedRun.started_at ?? ""),
        status: selectedRun.status,
        summary: `检视运行开始：${selectedRun.status}`,
        review_job_id: selectedRun.review_job_id,
        head_sha: selectedRun.head_sha,
        analysis_mode: selectedRun.analysis_mode,
        risk_snapshot_json: selectedRun.risk_snapshot_json
      });
      if (selectedRun.completed_at) {
        items.push({
          kind: "review_run_completed",
          id: selectedRun.id,
          timestamp: String(selectedRun.completed_at),
          status: selectedRun.status,
          summary: `检视运行结束：${selectedRun.status}`,
          report_summary: selectedRun.report_summary,
          budget_used_json: selectedRun.budget_used_json,
          quality_metrics_json: selectedRun.quality_metrics_json
        });
      }

      for (const row of all<Record<string, any>>(`
        SELECT e.*, s.span_key, s.agent_id, s.status AS span_status
        FROM agent_trace_events e
        JOIN agent_trace_spans s ON s.id = e.span_id
        WHERE s.review_run_id = ?
        ORDER BY e.created_at
      `, [selectedRun.id])) {
        items.push({
          kind: "trace_event",
          id: row.id,
          timestamp: row.created_at,
          status: row.span_status,
          summary: row.summary,
          span_id: row.span_id,
          span_key: row.span_key,
          agent_id: row.agent_id,
          event_type: row.event_type,
          payload_json: row.payload_json
        });
      }

      for (const row of all<Record<string, any>>(`
        SELECT msg.*, s.span_key, s.agent_id
        FROM agent_messages msg
        JOIN agent_trace_spans s ON s.id = msg.span_id
        WHERE s.review_run_id = ?
        ORDER BY msg.created_at
      `, [selectedRun.id])) {
        items.push({
          kind: "agent_message",
          id: row.id,
          timestamp: row.created_at,
          status: "recorded",
          summary: row.content_summary,
          span_id: row.span_id,
          span_key: row.span_key,
          agent_id: row.agent_id,
          from_agent: row.from_agent,
          to_agent: row.to_agent,
          role: row.role,
          artifact_id: row.artifact_id
        });
      }

      for (const row of all<Record<string, any>>(`
        SELECT t.*, s.span_key, s.agent_id
        FROM tool_call_records t
        JOIN agent_trace_spans s ON s.id = t.span_id
        WHERE s.review_run_id = ?
        ORDER BY t.created_at
      `, [selectedRun.id])) {
        items.push({
          kind: "tool_call",
          id: row.id,
          timestamp: row.created_at,
          status: row.status,
          summary: row.output_summary || row.args_summary || row.tool_name,
          span_id: row.span_id,
          span_key: row.span_key,
          agent_id: row.agent_id,
          tool_name: row.tool_name,
          tool_version: row.tool_version,
          args_summary: row.args_summary,
          input_ref_json: row.input_ref_json,
          output_summary: row.output_summary,
          output_ref_json: row.output_ref_json,
          duration_ms: row.duration_ms
        });
      }

      for (const row of all<Record<string, any>>(`
        SELECT l.*, s.span_key, s.agent_id
        FROM llm_call_records l
        JOIN agent_trace_spans s ON s.id = l.span_id
        WHERE s.review_run_id = ?
        ORDER BY l.created_at
      `, [selectedRun.id])) {
        items.push({
          kind: "llm_call",
          id: row.id,
          timestamp: row.created_at,
          status: row.status,
          summary: `${row.provider}/${row.model} ${row.status}`,
          span_id: row.span_id,
          span_key: row.span_key,
          agent_id: row.agent_id,
          provider: row.provider,
          model: row.model,
          request_id: row.request_id,
          prompt_hash: row.prompt_hash,
          input_tokens: row.input_tokens,
          output_tokens: row.output_tokens,
          duration_ms: row.duration_ms
        });
      }

      for (const row of all<Record<string, any>>(`
        SELECT m.*, s.span_key, s.agent_id
        FROM mcp_call_records m
        JOIN agent_trace_spans s ON s.id = m.span_id
        WHERE s.review_run_id = ?
        ORDER BY m.created_at
      `, [selectedRun.id])) {
        items.push({
          kind: "mcp_call",
          id: row.id,
          timestamp: row.created_at,
          status: row.status,
          summary: row.response_summary || row.request_summary || `${row.server_name}.${row.tool_name}`,
          span_id: row.span_id,
          span_key: row.span_key,
          agent_id: row.agent_id,
          server_name: row.server_name,
          tool_name: row.tool_name,
          request_summary: row.request_summary,
          response_summary: row.response_summary,
          duration_ms: row.duration_ms
        });
      }

      for (const row of all<Record<string, any>>("SELECT * FROM review_artifacts WHERE review_run_id = ? ORDER BY created_at", [selectedRun.id])) {
        items.push({
          kind: "artifact",
          id: row.id,
          timestamp: row.created_at,
          status: "recorded",
          summary: row.name,
          artifact_type: row.artifact_type,
          name: row.name,
          storage_uri: row.storage_uri,
          sha256: row.sha256,
          size_bytes: row.size_bytes,
          metadata_json: row.metadata_json
        });
      }
    }

    items.sort((left, right) => String(left.timestamp).localeCompare(String(right.timestamp)) || String(left.kind).localeCompare(String(right.kind)));
    return {
      mr_id: mrId,
      run_id: selectedRun?.id ?? null,
      latest_job: jobs[0] ?? null,
      runs: runs.map((run) => ({
        id: run.id,
        review_job_id: run.review_job_id,
        status: run.status,
        started_at: run.started_at,
        completed_at: run.completed_at,
        analysis_mode: run.analysis_mode
      })),
      counts: countByKind(items),
      items
    };
  }

  const routes: Route[] = [
    route("GET", "/api/mr-review/projects/:projectId/merge-requests", ({ params, url }) => {
      const status = url.searchParams.get("status");
      const activeJobStatuses = new Set(["fetching", "pre_scanning", "reviewing", "judging", "running"]);
      const activeProjectJob = get<Record<string, any>>(`
        SELECT rj.id AS job_id, rj.status, mr.id AS merge_request_id, mr.number, mr.title
        FROM review_jobs rj
        JOIN merge_requests mr ON mr.id = rj.merge_request_id
        JOIN repositories r ON r.id = mr.repository_id
        WHERE r.project_id = ?
          AND rj.status IN ('fetching', 'pre_scanning', 'reviewing', 'judging', 'running')
          AND COALESCE(rj.heartbeat_at, rj.locked_at, rj.updated_at) >= datetime('now', '-60 seconds')
        ORDER BY rj.locked_at DESC, rj.updated_at DESC
        LIMIT 1
      `, [params.projectId]);
      const rows = mergeRequestRepository.listByProject(params.projectId, null).map((row: any) => {
        const effectiveStatus = activeJobStatuses.has(String(row.latest_job_status)) ? String(row.latest_job_status) : String(row.review_status);
        const blockedByProject = effectiveStatus === "queued" && activeProjectJob && activeProjectJob.merge_request_id !== row.id;
        return {
          ...row,
          review_status: effectiveStatus,
          queue_blocked_by_project: Boolean(blockedByProject),
          queue_blocked_reason: blockedByProject
            ? `项目内 !${activeProjectJob.number} 正在检视，当前 MR 将排队等待`
            : "",
          active_project_review: blockedByProject ? activeProjectJob : null
        };
      });
      const filtered = status ? rows.filter((row: any) => row.review_status === status) : rows;
      return { items: filtered };
    }),
    route("POST", "/api/mr-review/projects/:projectId/sync", async ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "reviewer");
      if (denied) return denied;
      const result = await syncProject(params.projectId);
      auditLog({
        userId: actorId,
        projectId: params.projectId,
        action: "mr_review.sync",
        resourceType: "project",
        resourceId: params.projectId,
        summary: `synced ${result.merge_requests} merge requests, queued ${result.jobs_created} jobs`,
        metadata: { repositories: result.repositories, repository_results: result.repository_results, errors: result.errors }
      });
      return result;
    }),
    route("GET", "/api/mr-review/projects/:projectId/dead-letters", ({ params }) => ({
      items: all(`
        SELECT dl.*, r.name AS repository_name, mr.title AS merge_request_title, mr.number
        FROM review_jobs_dead_letter dl
        JOIN review_jobs rj ON rj.id = dl.review_job_id
        JOIN merge_requests mr ON mr.id = rj.merge_request_id
        JOIN repositories r ON r.id = mr.repository_id
        WHERE r.project_id = ?
        ORDER BY dl.created_at DESC
      `, [params.projectId])
    })),
    route("GET", "/api/mr-review/merge-requests/:mrId", ({ params }) => {
      const mr = mergeRequestRepository.findDetailById(params.mrId);
      if (!mr) return notFound();
      const jobs = reviewJobRepository.listByMergeRequest(params.mrId);
      const runs = all(`
        SELECT rr.* FROM review_runs rr
        JOIN review_jobs rj ON rj.id = rr.review_job_id
        WHERE rj.merge_request_id = ?
        ORDER BY rr.started_at DESC
      `, [params.mrId]);
      const latestRun = runs[0] as { id: string } | undefined;
      const findings = latestRun
        ? all("SELECT * FROM review_findings WHERE review_run_id = ? ORDER BY severity DESC, confidence DESC", [latestRun.id])
        : [];
      const toolObservations = latestRun
        ? all("SELECT * FROM tool_observations WHERE review_run_id = ? ORDER BY created_at", [latestRun.id])
        : [];
      const trace = latestRun
        ? all(`
            SELECT s.span_key, s.agent_id, s.status, e.event_type, e.summary, e.payload_json, e.created_at
            FROM agent_trace_spans s
            LEFT JOIN agent_trace_events e ON e.span_id = s.id
            WHERE s.review_run_id = ?
            ORDER BY s.started_at, e.created_at
          `, [latestRun.id])
        : [];
      const sessionLogs = latestRun
        ? {
            messages: all(`
              SELECT msg.*, s.span_key, s.agent_id
              FROM agent_messages msg
              JOIN agent_trace_spans s ON s.id = msg.span_id
              WHERE s.review_run_id = ?
              ORDER BY msg.created_at
            `, [latestRun.id]),
            tool_calls: all(`
              SELECT t.*, s.span_key, s.agent_id
              FROM tool_call_records t
              JOIN agent_trace_spans s ON s.id = t.span_id
              WHERE s.review_run_id = ?
              ORDER BY t.created_at
            `, [latestRun.id]),
            llm_calls: all(`
              SELECT l.*, s.span_key, s.agent_id
              FROM llm_call_records l
              JOIN agent_trace_spans s ON s.id = l.span_id
              WHERE s.review_run_id = ?
              ORDER BY l.created_at
            `, [latestRun.id]),
            mcp_calls: all(`
              SELECT m.*, s.span_key, s.agent_id
              FROM mcp_call_records m
              JOIN agent_trace_spans s ON s.id = m.span_id
              WHERE s.review_run_id = ?
              ORDER BY m.created_at
            `, [latestRun.id]),
            artifacts: all("SELECT * FROM review_artifacts WHERE review_run_id = ? ORDER BY created_at", [latestRun.id])
          }
        : { messages: [], tool_calls: [], llm_calls: [], mcp_calls: [], artifacts: [] };
      return { mr, jobs, runs, findings, tool_observations: toolObservations, trace, session_logs: sessionLogs, compare: compareRunsForMr(params.mrId) };
    }),
    route("DELETE", "/api/mr-review/merge-requests/:mrId", ({ params, req }) => {
      const actorId = currentUserId(req);
      const mr = mergeRequestRepository.findById(params.mrId);
      if (!mr) return notFound();
      const repo = repositoryRepository.findProjectByRepositoryId(mr.repository_id);
      if (!repo) return notFound();
      const denied = ensureProjectRole(repo.project_id, actorId, "reviewer");
      if (denied) return denied;
      const result = mergeRequestRepository.deleteById(params.mrId);
      if (!result.ok) return notFound();
      auditLog({
        userId: actorId,
        projectId: repo.project_id,
        action: "mr_review.delete",
        resourceType: "merge_request",
        resourceId: params.mrId,
        summary: `deleted local MR cache with ${result.deleted_jobs} jobs, ${result.deleted_runs} runs, ${result.deleted_findings} findings`,
        metadata: {
          repository_id: mr.repository_id,
          external_mr_id: mr.external_mr_id,
          deleted_related_rows: result.deleted_related_rows
        }
      });
      return { ...result, ok: true, mr_id: params.mrId };
    }),
    route("GET", "/api/mr-review/merge-requests/:mrId/logs", ({ params, req, url }) => {
      const mr = mergeRequestRepository.findDetailById(params.mrId) as any;
      if (!mr) return notFound();
      const repo = repositoryRepository.findProjectByRepositoryId(mr.repository_id) as { project_id: string } | undefined;
      if (!repo) return notFound();
      const denied = ensureProjectRole(repo.project_id, currentUserId(req), "developer");
      if (denied) return denied;
      return unifiedReviewLogs(params.mrId, url.searchParams.get("run_id"));
    }),
    route("GET", "/api/mr-review/merge-requests/:mrId/export.md", ({ params, req }) => {
      const mr = mergeRequestRepository.findDetailById(params.mrId) as any;
      if (!mr) return notFound();
      const repo = repositoryRepository.findProjectByRepositoryId(mr.repository_id) as { project_id: string } | undefined;
      if (!repo) return notFound();
      const denied = ensureProjectRole(repo.project_id, currentUserId(req), "developer");
      if (denied) return denied;
      const runs = all(`
        SELECT rr.* FROM review_runs rr
        JOIN review_jobs rj ON rj.id = rr.review_job_id
        WHERE rj.merge_request_id = ?
        ORDER BY rr.started_at DESC
      `, [params.mrId]);
      const latestRun = runs[0] as { id: string } | undefined;
      const findings = latestRun
        ? all<FindingRow>("SELECT * FROM review_findings WHERE review_run_id = ? ORDER BY severity DESC, confidence DESC", [latestRun.id])
        : [];
      const content = formatMrReviewMarkdown({ mr, run: latestRun as any, findings });
      auditLog({
        userId: currentUserId(req),
        projectId: repo.project_id,
        action: "mr_review.export_markdown",
        resourceType: "merge_request",
        resourceId: params.mrId,
        summary: `exported ${findings.length} findings as markdown`
      });
      return {
        filename: markdownFilename(mr),
        content_type: "text/markdown; charset=utf-8",
        content
      };
    }),
    route("POST", "/api/mr-review/merge-requests/:mrId/review-jobs", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const mr = mergeRequestRepository.findById(params.mrId);
      if (!mr) return notFound();
      const repo = repositoryRepository.findProjectByRepositoryId(mr.repository_id);
      if (!repo) return notFound();
      const denied = ensureProjectRole(repo.project_id, actorId, "reviewer");
      if (denied) return denied;
      const input = body as Record<string, unknown> | undefined;
      const job = reviewQueueService.enqueueOrReset({
        mergeRequestId: params.mrId,
        headSha: mr.latest_head_sha,
        priority: mr.risk_score,
        effortLevel: String(input?.effort_level ?? "standard"),
        requestedBy: actorId
      });
      mergeRequestRepository.updateReviewStatus(params.mrId, "queued");
      auditLog({ userId: actorId, projectId: repo.project_id, action: "mr_review.enqueue", resourceType: "merge_request", resourceId: params.mrId, summary: `enqueue ${input?.effort_level ?? "standard"} review` });
      runWorkerOnce();
      return job;
    }),
    route("POST", "/api/mr-review/merge-requests/:mrId/pause", ({ params, req }) => {
      const actorId = currentUserId(req);
      const mr = mergeRequestRepository.findById(params.mrId);
      if (!mr) return notFound();
      const repo = repositoryRepository.findProjectByRepositoryId(mr.repository_id);
      if (!repo) return notFound();
      const denied = ensureProjectRole(repo.project_id, actorId, "reviewer");
      if (denied) return denied;
      const result = reviewQueueService.pauseByMergeRequest(params.mrId);
      mergeRequestRepository.updateReviewStatus(params.mrId, "paused");
      auditLog({ userId: actorId, projectId: repo.project_id, action: "mr_review.pause", resourceType: "merge_request", resourceId: params.mrId, summary: `paused ${result.changes} review jobs` });
      return { ok: true, paused_jobs: result.changes };
    }),
    route("POST", "/api/mr-review/merge-requests/:mrId/stop", ({ params, req }) => {
      const actorId = currentUserId(req);
      const mr = mergeRequestRepository.findById(params.mrId);
      if (!mr) return notFound();
      const repo = repositoryRepository.findProjectByRepositoryId(mr.repository_id);
      if (!repo) return notFound();
      const denied = ensureProjectRole(repo.project_id, actorId, "reviewer");
      if (denied) return denied;
      const result = reviewQueueService.stopByMergeRequest(params.mrId);
      mergeRequestRepository.updateReviewStatus(params.mrId, "cancelled");
      auditLog({ userId: actorId, projectId: repo.project_id, action: "mr_review.stop", resourceType: "merge_request", resourceId: params.mrId, summary: `stopped ${result.changes} review jobs` });
      return { ok: true, stopped_jobs: result.changes };
    }),
    route("POST", "/api/mr-review/review-jobs/:jobId/retry", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const input = body as Record<string, unknown> | undefined;
      const job = reviewJobRepository.findWithProject(params.jobId) as { id: string; merge_request_id: string; requested_effort_level: string; project_id: string } | undefined;
      if (!job) return notFound();
      const denied = ensureProjectRole(job.project_id, actorId, "reviewer");
      if (denied) return denied;
      const updated = reviewQueueService.retry(params.jobId, String(input?.effort_level ?? job.requested_effort_level ?? "standard"), actorId);
      mergeRequestRepository.updateReviewStatus(job.merge_request_id, "queued");
      auditLog({ userId: actorId, projectId: job.project_id, action: "mr_review.retry", resourceType: "review_job", resourceId: params.jobId, summary: `retry as ${input?.effort_level ?? job.requested_effort_level ?? "standard"}` });
      runWorkerOnce();
      return updated;
    }),
    route("GET", "/api/mr-review/review-runs/:runId", ({ params }) =>
      get("SELECT * FROM review_runs WHERE id = ?", [params.runId]) ?? notFound()
    ),
    route("GET", "/api/mr-review/review-runs/:runId/trace", ({ params }) => ({
      items: all(`
        SELECT s.*, e.event_type, e.summary, e.payload_json, e.created_at AS event_created_at
        FROM agent_trace_spans s
        LEFT JOIN agent_trace_events e ON e.span_id = s.id
        WHERE s.review_run_id = ?
        ORDER BY s.started_at, e.created_at
      `, [params.runId])
    })),
    route("GET", "/api/mr-review/review-runs/:runId/session-logs", ({ params }) => {
      const spans = all("SELECT * FROM agent_trace_spans WHERE review_run_id = ? ORDER BY started_at", [params.runId]);
      const events = all(`
        SELECT e.*, s.span_key, s.agent_id
        FROM agent_trace_events e
        JOIN agent_trace_spans s ON s.id = e.span_id
        WHERE s.review_run_id = ?
        ORDER BY e.created_at
      `, [params.runId]);
      const llmCalls = all(`
        SELECT l.*, s.span_key, s.agent_id
        FROM llm_call_records l
        JOIN agent_trace_spans s ON s.id = l.span_id
        WHERE s.review_run_id = ?
        ORDER BY l.created_at
      `, [params.runId]);
      const toolCalls = all(`
        SELECT t.*, s.span_key, s.agent_id
        FROM tool_call_records t
        JOIN agent_trace_spans s ON s.id = t.span_id
        WHERE s.review_run_id = ?
        ORDER BY t.created_at
      `, [params.runId]);
      const mcpCalls = all(`
        SELECT m.*, s.span_key, s.agent_id
        FROM mcp_call_records m
        JOIN agent_trace_spans s ON s.id = m.span_id
        WHERE s.review_run_id = ?
        ORDER BY m.created_at
      `, [params.runId]);
      const messages = all(`
        SELECT msg.*, s.span_key, s.agent_id
        FROM agent_messages msg
        JOIN agent_trace_spans s ON s.id = msg.span_id
        WHERE s.review_run_id = ?
        ORDER BY msg.created_at
      `, [params.runId]);
      return { spans, events, messages, llm_calls: llmCalls, tool_calls: toolCalls, mcp_calls: mcpCalls };
    }),
    route("GET", "/api/mr-review/review-runs/:runId/artifacts", ({ params }) => ({
      items: all("SELECT * FROM review_artifacts WHERE review_run_id = ? ORDER BY created_at", [params.runId])
    })),
    route("GET", "/api/mr-review/merge-requests/:mrId/review-runs/compare", ({ params }) => {
      return compareRunsForMr(params.mrId);
    }),
    route("POST", "/api/mr-review/merge-requests/:mrId/external-reports", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const mr = mergeRequestRepository.findById(params.mrId);
      if (!mr) return notFound();
      const repo = repositoryRepository.findProjectByRepositoryId(mr.repository_id);
      if (!repo) return notFound();
      const denied = ensureProjectRole(repo.project_id, actorId, "reviewer");
      if (denied) return denied;
      const input = body as Record<string, unknown> | undefined;
      const reportType = String(input?.type ?? input?.report_type ?? "").trim();
      const reportFormat = String(input?.report_format ?? "").trim();
      const commitSha = String(input?.commit_sha ?? mr.latest_head_sha).trim();
      if (!reportType) return badRequest("type is required");
      if (!reportFormat) return badRequest("report_format is required");
      const reportId = id("ext_report");
      db.prepare(`
        INSERT INTO external_review_reports (
          id, merge_request_id, report_type, commit_sha, report_format, report_url,
          payload_json, metadata_json, status, created_by
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'received', ?)
      `).run(
        reportId,
        params.mrId,
        reportType,
        commitSha,
        reportFormat,
        input?.report_url ? String(input.report_url) : null,
        JSON.stringify(input?.payload ?? {}),
        JSON.stringify(input?.metadata ?? {}),
        actorId
      );
      auditLog({
        userId: actorId,
        projectId: repo.project_id,
        action: "mr_review.external_report.received",
        resourceType: "merge_request",
        resourceId: params.mrId,
        summary: `${reportType}:${reportFormat}`,
        metadata: { report_id: reportId, commit_sha: commitSha }
      });
      return get("SELECT * FROM external_review_reports WHERE id = ?", [reportId]);
    }),
    route("GET", "/api/mr-review/merge-requests/:mrId/external-reports", ({ params, req }) => {
      const actorId = currentUserId(req);
      const mr = mergeRequestRepository.findById(params.mrId);
      if (!mr) return notFound();
      const repo = repositoryRepository.findProjectByRepositoryId(mr.repository_id);
      if (!repo) return notFound();
      const denied = ensureProjectRole(repo.project_id, actorId, "observer");
      if (denied) return denied;
      return {
        items: all(
          "SELECT * FROM external_review_reports WHERE merge_request_id = ? ORDER BY created_at DESC",
          [params.mrId]
        )
      };
    }),
    route("PATCH", "/api/mr-review/review-findings/:findingId", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const input = body as Record<string, unknown>;
      const finding = get<FindingRow & { project_id: string }>(`
        SELECT rf.*, r.project_id
        FROM review_findings rf
        JOIN review_runs rr ON rr.id = rf.review_run_id
        JOIN review_jobs rj ON rj.id = rr.review_job_id
        JOIN merge_requests mr ON mr.id = rj.merge_request_id
        JOIN repositories r ON r.id = mr.repository_id
        WHERE rf.id = ?
      `, [params.findingId]);
      if (!finding) return notFound();
      const denied = ensureProjectRole(finding.project_id, actorId, "developer");
      if (denied) return denied;
      if (typeof input.selected === "boolean") {
        db.prepare("UPDATE review_findings SET selected = ? WHERE id = ?").run(input.selected ? 1 : 0, params.findingId);
        auditLog({ userId: actorId, projectId: finding.project_id, action: "finding.select", resourceType: "review_finding", resourceId: params.findingId, summary: `selected=${input.selected}` });
      }
      if (typeof input.lifecycle_state === "string") {
        db.prepare("UPDATE review_findings SET lifecycle_state = ? WHERE id = ?").run(input.lifecycle_state, params.findingId);
        auditLog({ userId: actorId, projectId: finding.project_id, action: "finding.lifecycle", resourceType: "review_finding", resourceId: params.findingId, summary: String(input.lifecycle_state) });
      }
      return get("SELECT * FROM review_findings WHERE id = ?", [params.findingId]);
    }),
    route("POST", "/api/mr-review/review-findings/:findingId/feedback", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const input = body as Record<string, unknown>;
      const state = String(input.feedback_type ?? "dismissed");
      const finding = get<FindingRow & { project_id: string }>(`
        SELECT rf.*, r.project_id
        FROM review_findings rf
        JOIN review_runs rr ON rr.id = rf.review_run_id
        JOIN review_jobs rj ON rj.id = rr.review_job_id
        JOIN merge_requests mr ON mr.id = rj.merge_request_id
        JOIN repositories r ON r.id = mr.repository_id
        WHERE rf.id = ?
      `, [params.findingId]);
      if (!finding) return notFound();
      const denied = ensureProjectRole(finding.project_id, actorId, "developer");
      if (denied) return denied;
      feedbackLearningService.markFindingFeedback(params.findingId, state);
      feedbackLearningService.recordFeedback({
        userId: actorId,
        finding,
        feedbackType: state,
        scope: String(input.scope ?? (state === "false_positive" ? "project" : "merge_request")),
        reason: input.reason ? String(input.reason) : null
      });
      auditLog({ userId: actorId, projectId: finding.project_id, action: "finding.feedback", resourceType: "review_finding", resourceId: params.findingId, summary: state, metadata: { scope: input.scope ?? null } });
      return get("SELECT * FROM review_findings WHERE id = ?", [params.findingId]);
    }),
    route("POST", "/api/mr-review/merge-requests/:mrId/publish", async ({ params, body, req }) => {
      const input = body as Record<string, unknown>;
      return publishFindings(params.mrId, (input.finding_ids as string[] | undefined) ?? [], Boolean(input.dry_run), currentUserId(req));
    }),
  ];
  return routes;
}
