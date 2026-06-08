import { randomBytes } from "node:crypto";
import { badRequest, id, notFound, route, sha1, type Route } from "../http.js";
import type { FindingRow } from "../types.js";
import type { BackendRouteContext } from "./context.js";

function parseJoltCommand(text: string) {
  const trimmed = text.trim();
  const match = trimmed.match(/^@jolt\s+(\S+)(?:\s+(.+))?$/i);
  if (!match) return null;
  return { command: match[1].toLowerCase(), arg: (match[2] ?? "").trim() };
}

function findingLocation(finding: FindingRow) {
  return `${finding.file_path}:${finding.line_start ?? "?"}${finding.line_end && finding.line_end !== finding.line_start ? `-${finding.line_end}` : ""}`;
}

function buildFindingExplanation(finding: FindingRow) {
  return [
    `@jolt explain ${finding.id}`,
    "",
    `问题：${finding.title}`,
    `位置：${findingLocation(finding)}`,
    `专家：${finding.agent_id}，置信度：${Number(finding.confidence).toFixed(2)}`,
    "",
    `原因：${finding.problem_description}`,
    "",
    `建议：${finding.recommendation}`,
    finding.suggested_code ? `\n建议代码：\n\`\`\`\n${finding.suggested_code}\n\`\`\`` : ""
  ].filter(Boolean).join("\n");
}

export function createWebhookRoutes(ctx: BackendRouteContext): Route[] {
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
    mrSyncService,
    reviewQueueService
  } = ctx;
  const routes: Route[] = [
    route("POST", "/api/mr-review/projects/:projectId/sync", async ({ params }) => syncProject(params.projectId)),
    route("POST", "/api/webhooks/:provider/:projectId/jolt-comment", async ({ params, body, req }) => {
      const provider = params.provider;
      if (!["github", "codehub"].includes(provider)) return badRequest("provider must be github or codehub");
      const input = body as Record<string, any>;
      const command = parseJoltCommand(String(input.comment_body ?? input.body ?? ""));
      if (!command) return badRequest("comment body must start with @jolt");
      const actorId = currentUserId(req);
      const mr = input.mr_id
        ? get<any>("SELECT mr.*, r.project_id, r.provider, r.provider_config_json FROM merge_requests mr JOIN repositories r ON r.id = mr.repository_id WHERE mr.id = ?", [String(input.mr_id)])
        : get<any>(
            "SELECT mr.*, r.project_id, r.provider, r.provider_config_json FROM merge_requests mr JOIN repositories r ON r.id = mr.repository_id WHERE r.project_id = ? AND r.provider = ? AND mr.number = ?",
            [params.projectId, provider, Number(input.mr_number ?? input.number ?? 0)]
          );
      if (!mr) return notFound();
      const denied = ensureProjectRole(mr.project_id, actorId, "developer");
      if (denied) return denied;
      let responseBody = "";
      if (command.command === "explain") {
        const finding = get<FindingRow>("SELECT * FROM review_findings WHERE id = ?", [command.arg]);
        if (!finding) return notFound();
        responseBody = buildFindingExplanation(finding);
      } else if (command.command === "dismiss") {
        const finding = get<FindingRow>("SELECT * FROM review_findings WHERE id = ?", [command.arg]);
        if (!finding) return notFound();
        db.prepare("UPDATE review_findings SET lifecycle_state = 'dismissed', selected = 0 WHERE id = ?").run(finding.id);
        responseBody = `@jolt dismiss\n\n已将 ${finding.id} 标记为 dismissed。`;
      } else if (command.command === "recheck") {
        reviewQueueService.enqueueOrReset({ mergeRequestId: mr.id, headSha: mr.latest_head_sha, priority: 1000, effortLevel: String(input.effort ?? "standard") });
        runWorkerOnce();
        responseBody = `@jolt recheck\n\n已重新入队检视 MR !${mr.number}，head_sha=${mr.latest_head_sha}。`;
      } else if (command.command === "why-not") {
        const [filePath, rawLine] = command.arg.split(":");
        const line = Number(rawLine ?? 0);
        const nearby = all<FindingRow>(
          `
          SELECT rf.*
          FROM review_findings rf
          JOIN review_runs rr ON rr.id = rf.review_run_id
          JOIN review_jobs rj ON rj.id = rr.review_job_id
          WHERE rj.merge_request_id = ? AND rf.file_path = ?
            AND (? = 0 OR rf.line_start IS NULL OR ABS(rf.line_start - ?) <= 5)
          ORDER BY rr.started_at DESC, rf.confidence DESC
          LIMIT 3
          `,
          [mr.id, filePath, line, line]
        );
        responseBody = nearby.length
          ? `@jolt why-not\n\n附近已有问题：\n${nearby.map((finding) => `- ${findingLocation(finding)} ${finding.title}`).join("\n")}`
          : `@jolt why-not\n\n当前最新检视没有在 ${command.arg} 附近输出问题。可能原因：未命中专家范围、证据不足、置信度低于阈值，或该行不在 MR diff 内。`;
      } else {
        return badRequest("unsupported @jolt command");
      }
      if (input.dry_run === false) {
        if (provider === "github") {
          const ref = await import("../github.js").then((github) => github.postIssueComment(config, repoConfig(mr), mr.number, responseBody));
          auditLog({ userId: actorId, projectId: mr.project_id, action: "jolt.chat.publish", resourceType: "merge_request", resourceId: mr.id, summary: command.command, metadata: { external_comment_id: ref.id } });
        } else {
          const ref = await import("../codehub.js").then((codehub) => codehub.postCodeHubSummaryComment(config, repoConfig(mr), mr.number, responseBody));
          auditLog({ userId: actorId, projectId: mr.project_id, action: "jolt.chat.publish", resourceType: "merge_request", resourceId: mr.id, summary: command.command, metadata: { external_comment_id: ref.id } });
        }
      } else {
        auditLog({ userId: actorId, projectId: mr.project_id, action: "jolt.chat.dry_run", resourceType: "merge_request", resourceId: mr.id, summary: command.command });
      }
      return { ok: true, provider, command: command.command, dry_run: input.dry_run !== false, body: responseBody };
    }),
    route("POST", "/api/webhooks/:provider/:projectId", ({ params, body, req }) => {
      const provider = params.provider;
      if (!["github", "codehub"].includes(provider)) return badRequest("provider must be github or codehub");
      const rawBody = typeof body === "string" ? body : JSON.stringify(body ?? {});
      const payloadSha = sha1(rawBody);
      const eventType = String(req.headers["x-github-event"] ?? req.headers["x-codehub-event"] ?? "unknown");
  
      const signature = Array.isArray(req.headers["x-hub-signature-256"])
        ? req.headers["x-hub-signature-256"][0]
        : req.headers["x-hub-signature-256"] ?? null;
  
      if (provider === "codehub") {
        const codehubSignature = Array.isArray(req.headers["x-codehub-signature"])
          ? req.headers["x-codehub-signature"][0]
          : req.headers["x-codehub-signature"] ?? signature ?? null;
        const webhookSecret = config.codehub?.webhook_secret;
        if (!verifyCodeHubSignature(webhookSecret, rawBody, codehubSignature)) {
          return { statusCode: 401, error: "invalid_signature" };
        }
  
        const payload = body as Record<string, any>;
        const normalized = normalizeCodeHubWebhookPayload(payload);
        if (!normalized.externalId || !normalized.number || !normalized.title || !normalized.headSha) {
          db.prepare(`
            INSERT INTO webhook_dead_letter (id, project_id, provider, event_type, payload_sha, failure_reason)
            VALUES (?, ?, ?, ?, ?, ?)
          `).run(
            id("webhook_dl"),
            params.projectId,
            provider,
            eventType,
            payloadSha,
            "CodeHub webhook payload lacks required MR fields"
          );
          return { ok: true, provider, status: "accepted_dead_letter", reason: "missing_required_fields" };
        }
  
        const repos = repositoryRepository.listActiveByProjectAndProvider(params.projectId, "codehub");
        const repo = repos.find((candidate) => codehubRepoMatches(candidate, normalized.repoFullName)) ?? repos[0];
        if (!repo) {
          db.prepare(`
            INSERT INTO webhook_dead_letter (id, project_id, provider, event_type, payload_sha, failure_reason)
            VALUES (?, ?, ?, ?, ?, ?)
          `).run(id("webhook_dl"), params.projectId, provider, eventType, payloadSha, `repository not bound: ${normalized.repoFullName || "<unknown>"}`);
          return { ok: true, provider, status: "ignored_unbound_repository", repository: normalized.repoFullName };
        }
  
        const existing = mergeRequestRepository.findByRepositoryAndExternalId(repo.id, normalized.externalId);
        const isClosed = ["closed", "merged", "merge_request close", "merge_request merge"].includes(normalized.action) ||
          ["closed", "merged"].includes(normalized.state);
        if (isClosed) {
          if (existing) {
            reviewQueueService.cancelQueued(existing.id);
            mergeRequestRepository.updateReviewStatus(existing.id, normalized.state === "merged" || normalized.action.includes("merge") ? "merged" : "closed");
          }
          return { ok: true, provider, normalized_event: normalized.state === "merged" ? "mr.merged" : "mr.closed" };
        }
  
        const result = mrSyncService.upsertAndEnqueue(repo, {
          externalId: normalized.externalId,
          number: normalized.number,
          title: normalized.title,
          author: normalized.author,
          sourceBranch: normalized.sourceBranch,
          targetBranch: normalized.targetBranch,
          headSha: normalized.headSha,
          htmlUrl: normalized.htmlUrl,
          additions: normalized.additions,
          deletions: normalized.deletions,
          changedFiles: normalized.changedFiles,
          metadata: {
            provider: "codehub",
            action: normalized.action,
            repository: normalized.repoFullName,
            additions: normalized.additions,
            deletions: normalized.deletions,
            changed_files: normalized.changedFiles
          }
        });
        if (result.jobCreated) runWorkerOnce();
        return { ok: true, provider, normalized_event: "mr.updated", job_created: result.jobCreated, merge_request_id: result.mergeRequestId };
      }
  
      const webhookSecret = config.github?.webhook_secret;
      if (!verifyGitHubSignature(webhookSecret, rawBody, signature)) {
        return { statusCode: 401, error: "invalid_signature" };
      }
  
      const payload = body as Record<string, any>;
      const action = String(payload?.action ?? "");
      const pull = payload?.pull_request;
      const repository = payload?.repository;
      if (!pull || !repository) return badRequest("GitHub pull_request payload is required");
  
      const fullName = String(repository.full_name ?? "");
      const repo = repositoryRepository.findByProjectProviderExternal(params.projectId, "github", fullName);
      if (!repo) {
        db.prepare(`
          INSERT INTO webhook_dead_letter (id, project_id, provider, event_type, payload_sha, failure_reason)
          VALUES (?, ?, ?, ?, ?, ?)
        `).run(id("webhook_dl"), params.projectId, provider, eventType, payloadSha, `repository not bound: ${fullName}`);
        return { ok: true, provider, status: "ignored_unbound_repository", repository: fullName };
      }
  
      if (["closed"].includes(action)) {
        const existing = mergeRequestRepository.findByRepositoryAndExternalId(repo.id, String(pull.id));
        if (existing) {
          reviewQueueService.cancelQueued(existing.id);
          mergeRequestRepository.updateReviewStatus(existing.id, pull.merged ? "merged" : "closed");
        }
        return { ok: true, provider, normalized_event: pull.merged ? "mr.merged" : "mr.closed" };
      }
  
      if (!["opened", "reopened", "synchronize"].includes(action)) {
        return { ok: true, provider, status: "ignored", action };
      }
  
      const result = mrSyncService.upsertAndEnqueue(repo, {
        externalId: String(pull.id),
        number: Number(pull.number),
        title: String(pull.title ?? ""),
        author: String(pull.user?.login ?? ""),
        sourceBranch: String(pull.head?.ref ?? ""),
        targetBranch: String(pull.base?.ref ?? ""),
        headSha: String(pull.head?.sha ?? ""),
        htmlUrl: String(pull.html_url ?? ""),
        additions: Number(pull.additions ?? 0),
        deletions: Number(pull.deletions ?? 0),
        changedFiles: Number(pull.changed_files ?? 0),
        metadata: {
          provider: "github",
          action,
          draft: Boolean(pull.draft),
          additions: Number(pull.additions ?? 0),
          deletions: Number(pull.deletions ?? 0),
          changed_files: Number(pull.changed_files ?? 0),
          base_sha: pull.base?.sha ?? ""
        }
      });
      if (result.jobCreated) runWorkerOnce();
      return { ok: true, provider, normalized_event: action === "synchronize" ? "mr.pushed" : `mr.${action}`, job_created: result.jobCreated };
    }),
    route("POST", "/api/webhooks/github/:projectId", ({ params, body, req, url, res }) => {
      const matched = routes.find((candidate) => candidate.method === "POST" && candidate.pattern.test(`/api/webhooks/github/${params.projectId}`));
      return matched?.handler({ params: { provider: "github", projectId: params.projectId }, body, req, url, res });
    }),
    route("POST", "/api/webhooks/codehub/:projectId", ({ params, body, req, url, res }) => {
      const matched = routes.find((candidate) => candidate.method === "POST" && candidate.pattern.test(`/api/webhooks/codehub/${params.projectId}`));
      return matched?.handler({ params: { provider: "codehub", projectId: params.projectId }, body, req, url, res });
    }),
  ];
  return routes;
}
