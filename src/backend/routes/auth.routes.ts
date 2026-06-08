import { randomBytes } from "node:crypto";
import { badRequest, id, notFound, route, sha1, type Route } from "../http.js";
import type { FindingRow } from "../types.js";
import type { BackendRouteContext } from "./context.js";

export function createAuthRoutes(ctx: BackendRouteContext): Route[] {
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
  const routes: Route[] = [
    route("POST", "/api/auth/login", ({ body }) => {
      const input = body as Record<string, unknown>;
      const username = String(input.username ?? "local-admin").trim();
      const user = projectRepository.findActiveUserByUsername(username) as { id: string; username: string; display_name: string } | undefined;
      if (!user) return { statusCode: 401, error: "invalid_user", message: "active user is required" };
      const token = randomBytes(32).toString("hex");
      projectRepository.createAuthSession(id("session"), user.id, sha1(token));
      auditLog({ userId: user.id, action: "auth.login", resourceType: "user", resourceId: user.id, summary: `${username} logged in` });
      return { token, user };
    }),
    route("GET", "/api/auth/session", ({ req }) => {
      const userId = currentUserId(req);
      const user = projectRepository.findUserById(userId);
      return { user, authenticated: Boolean(user) };
    }),
    route("POST", "/api/auth/logout", ({ req }) => {
      const token = bearerToken(req);
      if (token) {
        projectRepository.revokeSession(sha1(token));
      }
      auditLog({ userId: currentUserId(req), action: "auth.logout", resourceType: "session", summary: "session revoked" });
      return { ok: true };
    }),
    route("GET", "/api/me", ({ req }) => {
      const userId = currentUserId(req);
      const user = projectRepository.findUserById(userId);
      const projects = projectRepository.listProjectsForUser(userId);
      return { user, projects };
    }),
  ];
  return routes;
}
