import { route, type Route } from "../http.js";

export function createHealthRoutes(options: { serviceName?: string } = {}): Route[] {
  return [
    route("GET", "/api/health", () => ({
      ok: true,
      service: options.serviceName ?? "jolt-common-backend"
    }))
  ];
}
