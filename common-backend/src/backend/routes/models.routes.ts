import { badRequest, route, type Route } from "../http.js";
import type { BackendRouteContext } from "./context.js";

const MODEL_SETTING_KEY = "llm_policy";

function internalToken() {
  return String(process.env.JOLT_INTERNAL_SERVICE_TOKEN || "").trim();
}

function requestInternalToken(req: { headers: Record<string, any> }) {
  const raw = req.headers["x-internal-service-token"];
  return String(Array.isArray(raw) ? raw[0] : raw || "").trim();
}

function ensureInternal(req: { headers: Record<string, any> }) {
  const expected = internalToken();
  if (!expected || requestInternalToken(req) !== expected) {
    return { statusCode: 401, error: "unauthorized", message: "internal service token is required" };
  }
  return null;
}

function sanitizeLlmConfig(value: Record<string, unknown>) {
  const { default_api_key: _ignored, ...rest } = value;
  return rest;
}

function sanitizeEffectiveConfig(value: Record<string, unknown>) {
  const next = JSON.parse(JSON.stringify(value ?? {})) as Record<string, unknown>;
  if (next.llm && typeof next.llm === "object") {
    next.llm = sanitizeLlmConfig(next.llm as Record<string, unknown>);
  }
  return next;
}

export function createModelRoutes(ctx: BackendRouteContext): Route[] {
  const { currentUserId, ensureRoot, projectConfigService, auditLog } = ctx;
  return [
    route("GET", "/api/models/effective-config", ({ req, url }) => {
      const actorId = currentUserId(req);
      const denied = ensureRoot(actorId);
      if (denied) return denied;
      const projectId = url.searchParams.get("project_id") || "project_default";
      const effective = projectConfigService.effectiveConfig(projectId, ctx.config).effective_config;
      return {
        project_id: projectId,
        llm: sanitizeLlmConfig((effective.llm ?? {}) as Record<string, unknown>),
        effective_config: sanitizeEffectiveConfig(effective as Record<string, unknown>)
      };
    }),
    route("PATCH", "/api/models/projects/:projectId", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureRoot(actorId);
      if (denied) return denied;
      const input = (typeof body === "object" && body ? body : {}) as Record<string, unknown>;
      const value = sanitizeLlmConfig({
        default_provider: input.default_provider,
        default_base_url: input.default_base_url,
        default_model: input.default_model,
        default_api_key_env: input.default_api_key_env,
        request_timeout_seconds: input.request_timeout_seconds,
        max_output_tokens: input.max_output_tokens,
        enable_stream: input.enable_stream
      });
      if (!String(value.default_provider ?? "").trim()) return badRequest("default_provider is required");
      if (!String(value.default_base_url ?? "").trim()) return badRequest("default_base_url is required");
      if (!String(value.default_model ?? "").trim()) return badRequest("default_model is required");
      const row = projectConfigService.upsertSetting(params.projectId, MODEL_SETTING_KEY, value);
      auditLog({
        userId: actorId,
        projectId: params.projectId,
        action: "models.project.update",
        resourceType: "project_settings",
        resourceId: MODEL_SETTING_KEY,
        summary: "updated project model configuration"
      });
      return row ? { key: row.key, value: sanitizeLlmConfig(JSON.parse(row.settings_json || "{}")), updated_at: row.updated_at } : { statusCode: 404, error: "not_found" };
    }),
    route("GET", "/internal/models/effective-config", ({ req, url }) => {
      const denied = ensureInternal(req);
      if (denied) return denied;
      const projectId = url.searchParams.get("project_id") || "project_default";
      const effective = projectConfigService.effectiveConfig(projectId, ctx.config).effective_config;
      return {
        project_id: projectId,
        llm: sanitizeLlmConfig((effective.llm ?? {}) as Record<string, unknown>),
        effective_config: sanitizeEffectiveConfig(effective as Record<string, unknown>)
      };
    })
  ];
}
