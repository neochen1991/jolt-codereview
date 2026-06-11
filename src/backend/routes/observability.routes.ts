import { route, type Route } from "../http.js";
import type { BackendRouteContext } from "./context.js";

export function createObservabilityRoutes(ctx: BackendRouteContext): Route[] {
  const { currentUserId, ensureProjectRole, observabilityService, staticToolAvailabilityService } = ctx;
  return [
    route("GET", "/api/projects/:projectId/queue/summary", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return observabilityService.queueSummary(params.projectId);
    }),
    route("GET", "/api/projects/:projectId/toolchain/status", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return observabilityService.toolchainStatus(params.projectId);
    }),
    route("GET", "/api/projects/:projectId/static-tools/availability", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return staticToolAvailabilityService.listAvailability();
    }),
    route("GET", "/api/projects/:projectId/agents/quality", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return observabilityService.agentQuality(params.projectId);
    })
  ];
}
