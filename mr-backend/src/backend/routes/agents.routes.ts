import { randomBytes } from "node:crypto";
import { badRequest, id, notFound, route, sha1, type Route } from "../http.js";
import type { FindingRow } from "../types.js";
import type { BackendRouteContext } from "./context.js";

function normalizeAgentKey(value: string) {
  const normalized = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 80);
  if (!normalized) return "";
  return normalized.endsWith("_agent") ? normalized : `${normalized}_agent`;
}

function listFromInput(value: unknown) {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
  return String(value ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function createAgentRoutes(ctx: BackendRouteContext): Route[] {
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
    agentConfigService,
    agentToolBindingService
  } = ctx;
  const routes: Route[] = [
    route("GET", "/api/projects/:projectId/agents", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return agentConfigService.listAgents(params.projectId);
    }),
    route("GET", "/api/projects/:projectId/expert-profiles", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return agentConfigService.listExpertProfiles(params.projectId);
    }),
    route("POST", "/api/projects/:projectId/expert-profiles", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      const input = body as Record<string, unknown>;
      const agentKey = normalizeAgentKey(String(input.agent_key ?? input.display_name ?? ""));
      if (!agentKey) return badRequest("agent_key or display_name is required");
      const displayName = String(input.display_name ?? agentKey);
      const roleProfile = String(input.role_profile ?? input.prompt ?? "自定义代码检视专家");
      const responsibilityScope = String(input.responsibility_scope ?? "按团队自定义规范检视当前 MR。");
      const excludedScope = String(input.excluded_scope ?? "不输出无法定位到当前 MR diff 精确行的问题。");
      const languages = listFromInput(input.languages);
      const paths = listFromInput(input.paths);
      const triggers = listFromInput(input.triggers);
      const customPrompt = String(input.custom_prompt ?? input.prompt ?? "");
      const created = agentConfigService.createCustomAgent({
        id: id("agent"),
        profileId: id("expert"),
        projectId: params.projectId,
        agentKey,
        displayName,
        roleProfile,
        responsibilityScope,
        excludedScope,
        appliesTo: {
          persona: roleProfile,
          exclusive_scope: String(input.exclusive_scope ?? agentKey.replace(/_agent$/, "")),
          review_scope: responsibilityScope,
          excluded_scope: excludedScope,
          custom_prompt: customPrompt,
          languages,
          paths,
          triggers
        },
        tools: listFromInput(input.tools),
        skills: listFromInput(input.skills),
        ruleSets: listFromInput(input.rule_sets),
        requiresDeepagents: input.requires_deepagents === undefined ? true : Boolean(input.requires_deepagents),
        minConfidence: Number(input.min_confidence ?? 0.75),
        maxFindings: Number(input.max_findings ?? 12),
        maxLlmCalls: Number(input.max_llm_calls ?? 6),
        maxToolCalls: Number(input.max_tool_calls ?? 12)
      });
      auditLog({ userId: actorId, projectId: params.projectId, action: "expert_profiles.create", resourceType: "expert_profile", resourceId: agentKey, summary: `created custom agent ${agentKey}` });
      return created;
    }),
    route("PATCH", "/api/projects/:projectId/expert-profiles/:agentKey", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      const current = agentConfigService.findExpertProfile(params.projectId, params.agentKey);
      if (!current) return notFound();
      const updated = agentConfigService.updateExpertProfile(params.projectId, params.agentKey, body as Record<string, unknown>);
      auditLog({ userId: actorId, projectId: params.projectId, action: "expert_profiles.update", resourceType: "expert_profile", resourceId: params.agentKey, summary: "updated expert profile" });
      return updated;
    }),
    route("GET", "/api/projects/:projectId/expert-tool-bindings", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return agentToolBindingService.listBindings(params.projectId);
    }),
    route("POST", "/api/projects/:projectId/expert-tool-bindings", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      const input = body as Record<string, unknown>;
      const agentKey = String(input.agent_key ?? "");
      const toolName = String(input.tool_name ?? "");
      if (!agentKey) return badRequest("agent_key is required");
      if (!toolName) return badRequest("tool_name is required");
      const items = agentToolBindingService.upsertBinding({
        id: id("tool_binding"),
        projectId: params.projectId,
        agentKey,
        toolName,
        permissionLevel: String(input.permission_level ?? "read_only"),
        maxCalls: Number(input.max_calls ?? 5),
        enabled: input.enabled === undefined ? true : Boolean(input.enabled)
      });
      auditLog({ userId: actorId, projectId: params.projectId, action: "expert_tool_bindings.upsert", resourceType: "expert_tool_binding", resourceId: `${agentKey}:${toolName}`, summary: `bind ${toolName} to ${agentKey}` });
      return { items };
    }),
    route("PATCH", "/api/projects/:projectId/agents/:agentId", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      const input = body as Record<string, unknown>;
      const current = agentConfigService.findAgent(params.projectId, params.agentId);
      if (!current) return notFound();
      const updated = agentConfigService.updateAgent(params.projectId, params.agentId, input);
      auditLog({ userId: actorId, projectId: params.projectId, action: "agents.update", resourceType: "agent_config", resourceId: params.agentId, summary: "updated agent config" });
      return updated;
    }),
  ];
  return routes;
}
