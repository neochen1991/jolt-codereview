import { route, type Route } from "../http.js";
import type { BackendRouteContext } from "./context.js";

export function createObservabilityRoutes(ctx: BackendRouteContext): Route[] {
  const { observabilityService, staticToolAvailabilityService } = ctx;
  return [
    route("GET", "/api/projects/:projectId/queue/summary", ({ params }) =>
      observabilityService.queueSummary(params.projectId)
    ),
    route("GET", "/api/projects/:projectId/toolchain/status", ({ params }) =>
      observabilityService.toolchainStatus(params.projectId)
    ),
    route("GET", "/api/projects/:projectId/static-tools/availability", () =>
      staticToolAvailabilityService.listAvailability()
    ),
    route("GET", "/api/projects/:projectId/agents/quality", ({ params }) =>
      observabilityService.agentQuality(params.projectId)
    )
  ];
}
