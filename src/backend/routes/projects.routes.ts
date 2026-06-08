import { badRequest, id, notFound, route, sha1, type Route } from "../http.js";
import type { FindingRow } from "../types.js";
import type { BackendRouteContext } from "./context.js";

type LlmTestInput = {
  default_provider?: string;
  default_base_url?: string;
  default_model?: string;
  default_api_key_env?: string | null;
  default_api_key?: string | null;
  request_timeout_seconds?: number;
  enable_stream?: boolean;
};

function openAiCompatibleChatUrl(baseUrl: string) {
  const normalized = baseUrl.trim().replace(/\/+$/, "");
  return `${normalized}/chat/completions`;
}

function resolveLlmApiKey(input: LlmTestInput) {
  const envName = typeof input.default_api_key_env === "string" ? input.default_api_key_env.trim() : "";
  if (envName && process.env[envName]) return process.env[envName] ?? "";
  return typeof input.default_api_key === "string" ? input.default_api_key.trim() : "";
}

function compactLlmTestInput(input: LlmTestInput) {
  const compacted: LlmTestInput = {};
  for (const [key, rawValue] of Object.entries(input) as Array<[keyof LlmTestInput, unknown]>) {
    if (rawValue === null || rawValue === undefined) continue;
    if (typeof rawValue === "string" && rawValue.trim() === "") continue;
    (compacted as Record<string, unknown>)[key] = rawValue;
  }
  return compacted;
}

function parseOpenAiLikeResponse(text: string, stream: boolean) {
  if (!stream) {
    try {
      return text ? JSON.parse(text) as Record<string, unknown> : null;
    } catch {
      return null;
    }
  }
  let sample = "";
  let chunkCount = 0;
  let parsedStatus: Record<string, unknown> | null = null;
  if (!text.split(/\r?\n/).some((line) => line.trim().startsWith("data:"))) {
    try {
      return text ? JSON.parse(text) as Record<string, unknown> : null;
    } catch {
      return null;
    }
  }
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line.startsWith("data:")) continue;
    const payload = line.slice(5).trim();
    if (!payload || payload === "[DONE]") continue;
    try {
      const chunk = JSON.parse(payload) as Record<string, unknown>;
      parsedStatus = chunk;
      chunkCount += 1;
      const choices = Array.isArray(chunk.choices) ? chunk.choices as Array<Record<string, unknown>> : [];
      const delta = choices[0]?.delta as Record<string, unknown> | undefined;
      if (typeof delta?.content === "string") sample += delta.content;
    } catch {
      continue;
    }
  }
  return {
    choices: [{ message: { content: sample } }],
    stream: { enabled: true, chunk_count: chunkCount },
    last_chunk: parsedStatus
  };
}

async function testOpenAiCompatibleLlm(input: LlmTestInput) {
  const baseUrl = String(input.default_base_url ?? "").trim();
  const model = String(input.default_model ?? "").trim();
  const apiKey = resolveLlmApiKey(input);
  if (!baseUrl) return badRequest("LLM base url is required");
  if (!model) return badRequest("LLM model is required");
  if (!apiKey) return badRequest("LLM api key or api key env is required");

  const started = Date.now();
  const controller = new AbortController();
  const configuredTimeout = Number(input.request_timeout_seconds ?? 120);
  const timeoutSeconds = Number.isFinite(configuredTimeout) ? Math.max(1, Math.min(600, configuredTimeout)) : 120;
  const enableStream = input.enable_stream !== false;
  const timer = setTimeout(() => controller.abort(), timeoutSeconds * 1000);
  try {
    const response = await fetch(openAiCompatibleChatUrl(baseUrl), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: enableStream ? "text/event-stream, application/json" : "application/json",
        Authorization: `Bearer ${apiKey}`
      },
      signal: controller.signal,
      body: JSON.stringify({
        model,
        messages: [
          { role: "system", content: "You are a connectivity checker. Reply with ok." },
          { role: "user", content: "ping" }
        ],
        temperature: 0,
        max_tokens: 8,
        stream: enableStream,
        ...(enableStream ? { stream_options: { include_usage: true } } : {})
      })
    });
    const text = await response.text();
    const parsed = parseOpenAiLikeResponse(text, enableStream);
    const choices = Array.isArray(parsed?.choices) ? parsed.choices as Array<Record<string, unknown>> : [];
    const firstMessage = choices[0]?.message as Record<string, unknown> | undefined;
    const sample = String(firstMessage?.content ?? "").slice(0, 80);
    return {
      ok: response.ok,
      provider: String(input.default_provider ?? ""),
      model,
      stream: enableStream,
      status: response.status,
      latency_ms: Date.now() - started,
      sample,
      error_preview: response.ok ? "" : text.slice(0, 300)
    };
  } catch (error) {
    return {
      ok: false,
      provider: String(input.default_provider ?? ""),
      model,
      status: 0,
      latency_ms: Date.now() - started,
      error_preview: error instanceof Error ? error.message : String(error)
    };
  } finally {
    clearTimeout(timer);
  }
}

export function createProjectRoutes(ctx: BackendRouteContext): Route[] {
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
    projectConfigService
  } = ctx;
  const routes: Route[] = [
    route("GET", "/api/projects", () => projectRepository.listProjects()),
    route("GET", "/api/projects/:projectId", ({ params }) => projectRepository.findProjectById(params.projectId) ?? notFound()),
    route("PATCH", "/api/projects/:projectId", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      const input = body as Record<string, unknown>;
      if (input.name !== undefined && !String(input.name).trim()) return badRequest("project name is required");
      const project = projectRepository.updateProject(params.projectId, {
        name: input.name !== undefined ? String(input.name).trim() : undefined,
        description: input.description !== undefined ? String(input.description) : undefined,
        data_policy: input.data_policy
      });
      auditLog({ userId: actorId, projectId: params.projectId, action: "projects.update", resourceType: "project", resourceId: params.projectId, summary: "updated project profile" });
      return project ?? notFound();
    }),
    route("GET", "/api/projects/:projectId/members", ({ params }) =>
      projectRepository.listMembers(params.projectId)
    ),
    route("POST", "/api/projects/:projectId/members", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      const input = body as Record<string, unknown>;
      const username = String(input.username ?? "").trim();
      const displayName = String(input.display_name ?? username);
      const role = String(input.role ?? "developer");
      if (!username) return badRequest("username is required");
      const userId = String(input.user_id ?? `user_${sha1(username).slice(0, 12)}`);
      const memberId = String(input.member_id ?? `member_${sha1(`${params.projectId}:${userId}`).slice(0, 12)}`);
      const member = projectRepository.upsertMember({
        userId,
        username,
        displayName,
        email: input.email ? String(input.email) : null,
        memberId,
        projectId: params.projectId,
        role
      });
      auditLog({ userId: actorId, projectId: params.projectId, action: "project.members.upsert", resourceType: "project_member", resourceId: memberId, summary: `upsert member ${username} as ${role}` });
      return member;
    }),
    route("PATCH", "/api/projects/:projectId/members/:memberId", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      const input = body as Record<string, unknown>;
      if (typeof input.role === "string") {
        projectRepository.updateMemberRole(params.projectId, params.memberId, input.role);
        auditLog({ userId: actorId, projectId: params.projectId, action: "project.members.update_role", resourceType: "project_member", resourceId: params.memberId, summary: `role=${input.role}` });
      }
      return projectRepository.findMember(params.projectId, params.memberId) ?? notFound();
    }),
    route("DELETE", "/api/projects/:projectId/members/:memberId", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      projectRepository.deleteMember(params.projectId, params.memberId);
      auditLog({ userId: actorId, projectId: params.projectId, action: "project.members.remove", resourceType: "project_member", resourceId: params.memberId });
      return { ok: true };
    }),
    route("GET", "/api/projects/:projectId/settings", ({ params }) =>
      projectConfigService.listSettings(params.projectId)
    ),
    route("GET", "/api/projects/:projectId/effective-config", ({ params }) =>
      projectConfigService.effectiveConfig(params.projectId, config)
    ),
    route("POST", "/api/projects/:projectId/settings/llm/test", async ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      const effective = projectConfigService.effectiveConfig(params.projectId, config).effective_config;
      const input = (typeof body === "object" && body ? body : {}) as LlmTestInput;
      const llm = {
        ...(effective.llm ?? {}),
        ...compactLlmTestInput(input)
      };
      const result = await testOpenAiCompatibleLlm(llm);
      auditLog({
        userId: actorId,
        projectId: params.projectId,
        action: "project.settings.llm_test",
        resourceType: "project_settings",
        resourceId: "llm_policy",
        summary: `tested llm provider=${String(llm.default_provider ?? "")} model=${String(llm.default_model ?? "")}`
      });
      return result;
    }),
    route("PATCH", "/api/projects/:projectId/settings/:key", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      if (!projectConfigService.isAllowedKey(params.key)) {
        return badRequest(`settings key must be one of: ${projectConfigService.allowedKeys().join(", ")}`);
      }
      const input = (body as Record<string, unknown> | undefined) ?? {};
      const value = (typeof input.value === "object" && input.value ? input.value : input) as Record<string, unknown>;
      const row = projectConfigService.upsertSetting(params.projectId, params.key, value);
      auditLog({
        userId: actorId,
        projectId: params.projectId,
        action: "project.settings.update",
        resourceType: "project_settings",
        resourceId: params.key,
        summary: `updated ${params.key}`
      });
      return row ? { key: row.key, value: JSON.parse(row.settings_json || "{}"), updated_at: row.updated_at } : notFound();
    }),
    route("GET", "/api/projects/:projectId/audit-logs", ({ params, url }) => {
      const limit = Math.min(100, Math.max(1, Number(url.searchParams.get("limit") ?? 50)));
      return {
        items: auditRepository.listForProject(params.projectId, limit)
      };
    }),
  ];
  return routes;
}
