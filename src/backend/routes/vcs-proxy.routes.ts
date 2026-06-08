import { badRequest, notFound, route, type Route } from "../http.js";
import type { MergeRequestRow } from "../types.js";
import { CodeHubProvider } from "../vcs/CodeHubProvider.js";
import { GithubProvider } from "../vcs/GithubProvider.js";
import type { VcsProvider } from "../vcs/VcsProvider.js";
import type { BackendRouteContext } from "./context.js";

export function createVcsProxyRoutes(ctx: BackendRouteContext): Route[] {
  const { config, get } = ctx;

  function providerFor(repository: { provider: string }): VcsProvider {
    if (repository.provider === "github") return new GithubProvider(config);
    if (repository.provider === "codehub") return new CodeHubProvider(config);
    throw new Error(`Unsupported VCS provider: ${repository.provider}`);
  }

  function mrContext(projectId: string, mrId: string) {
    const row = get<Record<string, unknown>>(
      `
      SELECT mr.*, r.provider, r.provider_config_json, r.project_id, r.external_repo_id, r.name, r.default_branch, r.status, r.created_at
      FROM merge_requests mr
      JOIN repositories r ON r.id = mr.repository_id
      WHERE mr.id = ? AND r.project_id = ?
      `,
      [mrId, projectId]
    );
    if (!row) return null;
    const mr = row as unknown as MergeRequestRow;
    const repository = {
      id: String(row.repository_id),
      project_id: String(row.project_id),
      provider: String(row.provider),
      external_repo_id: String(row.external_repo_id),
      name: String(row.name),
      default_branch: String(row.default_branch),
      status: String(row.status),
      provider_config_json: String(row.provider_config_json || "{}"),
      created_at: String(row.created_at || ""),
      updated_at: String(row.updated_at || ""),
    };
    return {
      mr,
      repository,
      provider: providerFor(repository),
      ref: {
        repository,
        number: Number(mr.number),
        externalId: mr.external_mr_id,
        headSha: mr.latest_head_sha,
      },
    };
  }

  return [
    route("GET", "/api/vcs/:projectId/capabilities", ({ params }) => {
      const rows = ctx.all<{ provider: string }>("SELECT DISTINCT provider FROM repositories WHERE project_id = ?", [params.projectId]);
      return {
        project_id: params.projectId,
        providers: rows.map((row) => {
          const provider = providerFor({ provider: row.provider });
          return { provider: row.provider, capabilities: provider.capabilities() };
        }),
      };
    }),

    route("GET", "/api/vcs/:projectId/merge-requests/:mrId/diff", async ({ params }) => {
      const context = mrContext(params.projectId, params.mrId);
      if (!context) return notFound();
      return context.provider.fetchDiff(context.ref);
    }),

    route("GET", "/api/vcs/:projectId/merge-requests/:mrId/files", async ({ params }) => {
      const context = mrContext(params.projectId, params.mrId);
      if (!context) return notFound();
      return { items: await context.provider.fetchFiles(context.ref) };
    }),

    route("GET", "/api/vcs/:projectId/merge-requests/:mrId/file", async ({ params, url }) => {
      const context = mrContext(params.projectId, params.mrId);
      if (!context) return notFound();
      const path = url.searchParams.get("path");
      if (!path) return badRequest("path is required");
      const sha = url.searchParams.get("sha") || context.ref.headSha;
      const content = await context.provider.fetchFile(context.ref, path, sha);
      return { path, sha, content, size: content.length };
    }),

    route("POST", "/api/vcs/:projectId/merge-requests/:mrId/comment", async ({ params, body }) => {
      const context = mrContext(params.projectId, params.mrId);
      if (!context) return notFound();
      const input = body as { body?: string; file_path?: string; line?: number };
      if (!input.body) return badRequest("comment body is required");
      return context.provider.postComment(context.ref, {
        body: input.body,
        filePath: input.file_path,
        line: input.line,
      });
    }),

    route("POST", "/api/vcs/:projectId/merge-requests/:mrId/status", async ({ params, body }) => {
      const context = mrContext(params.projectId, params.mrId);
      if (!context) return notFound();
      const input = body as { state?: "pending" | "running" | "success" | "failed" | "warning"; description?: string; target_url?: string; context?: string };
      if (!input.state || !input.description) return badRequest("state and description are required");
      await context.provider.updateStatus(context.ref, {
        state: input.state,
        description: input.description,
        targetUrl: input.target_url,
        context: input.context,
      });
      return { ok: true };
    }),
  ];
}
