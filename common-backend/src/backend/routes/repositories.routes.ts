import { badRequest, id, notFound, route, type Route } from "../http.js";
import { inferProviderFromGitUrl, parseGitRepositoryUrl, repositoryConfigFromGitUrl, validateVcsEndpoint } from "../repositoryIdentity.js";
import type { BackendRouteContext } from "./context.js";

function tableExists(ctx: BackendRouteContext, tableName: string) {
  const row = ctx.get<{ name: string }>(`
    SELECT table_name AS name
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name = $1
  `, [tableName]);
  return Boolean(row);
}

function cancelQueuedReviewWork(ctx: BackendRouteContext, repositoryId: string) {
  if (!tableExists(ctx, "merge_requests")) return;
  if (tableExists(ctx, "review_jobs")) {
    ctx.db.prepare(`
      UPDATE review_jobs
      SET status = 'cancelled',
          updated_at = CURRENT_TIMESTAMP
      WHERE status = 'queued'
        AND merge_request_id IN (
          SELECT id FROM merge_requests WHERE repository_id = $1
        )
    `).run(repositoryId);
  }
  ctx.db.prepare(`
    UPDATE merge_requests
    SET review_status = 'cancelled',
        updated_at = CURRENT_TIMESTAMP
    WHERE repository_id = $1 AND review_status = 'queued'
  `).run(repositoryId);
}

export function createRepositoryRoutes(ctx: BackendRouteContext): Route[] {
  const { config, currentUserId, ensureProjectRole, repositoryRepository, auditLog } = ctx;
  return [
    route("GET", "/api/projects/:projectId/repositories", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "observer");
      if (denied) return denied;
      return repositoryRepository.listByProject(params.projectId);
    }),
    route("POST", "/api/projects/:projectId/repositories", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      const input = body as Record<string, unknown>;
      const rawGitUrl = String(input.git_url ?? input.external_repo_id ?? "");
      let parsed;
      try {
        parsed = parseGitRepositoryUrl(rawGitUrl);
      } catch (error) {
        return badRequest((error as Error).message);
      }
      const inferredProvider = inferProviderFromGitUrl(parsed);
      const provider = String(input.provider ?? inferredProvider ?? "github");
      const name = String(input.name ?? parsed.name);
      if (!["github", "codehub"].includes(provider)) return badRequest("provider must be github or codehub");
      const providerInput = typeof input.provider_config === "object" && input.provider_config ? input.provider_config : {};
      const providerConfig = repositoryConfigFromGitUrl(config, provider as "github" | "codehub", parsed, providerInput as Record<string, unknown>);
      const endpointError = validateVcsEndpoint(providerConfig.endpoint);
      if (endpointError) return badRequest(endpointError);
      const repository = repositoryRepository.upsert({
        id: id("repo"),
        projectId: params.projectId,
        provider,
        externalRepoId: parsed.gitUrl,
        name,
        defaultBranch: String(input.default_branch ?? "main"),
        providerConfig: providerConfig as unknown as Record<string, unknown>
      });
      auditLog({
        userId: actorId,
        projectId: params.projectId,
        action: "repositories.upsert",
        resourceType: "repository",
        resourceId: parsed.gitUrl,
        summary: `bound ${provider}:${parsed.gitUrl}`
      });
      return repository;
    }),
    route("DELETE", "/api/projects/:projectId/repositories/:repositoryId", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      const repository = repositoryRepository.findById(params.repositoryId);
      if (!repository || repository.project_id !== params.projectId || repository.status !== "active") return notFound();

      const result = repositoryRepository.softDelete(params.projectId, params.repositoryId);
      if (!result.changes) return notFound();
      cancelQueuedReviewWork(ctx, params.repositoryId);
      auditLog({
        userId: actorId,
        projectId: params.projectId,
        action: "repositories.delete",
        resourceType: "repository",
        resourceId: repository.external_repo_id,
        summary: `unbound ${repository.provider}:${repository.external_repo_id}`
      });
      return { ok: true, repository_id: params.repositoryId };
    })
  ];
}
