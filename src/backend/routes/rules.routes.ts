import { randomBytes } from "node:crypto";
import { badRequest, id, notFound, route, sha1, type Route } from "../http.js";
import type { FindingRow } from "../types.js";
import type { BackendRouteContext } from "./context.js";

function normalizeSkillKey(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

function normalizeSkillAssetPath(value: string) {
  return value
    .trim()
    .replace(/\\/g, "/")
    .replace(/^\/+/, "")
    .replace(/\/+/g, "/")
    .slice(0, 180);
}

function inferSkillAssetType(path: string, explicit?: unknown) {
  if (typeof explicit === "string" && explicit.trim()) return explicit.trim();
  if (path === "SKILL.md") return "skill";
  if (path.startsWith("references/")) return "reference";
  if (path.startsWith("scripts/")) return "script";
  if (path.startsWith("assets/")) return "asset";
  return "reference";
}

export function createRuleRoutes(ctx: BackendRouteContext): Route[] {
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
    route("GET", "/api/projects/:projectId/rule-sets", ({ params }) =>
      ruleDocumentRepository.listRuleSets(params.projectId)
    ),
    route("POST", "/api/projects/:projectId/rule-sets", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      const input = body as Record<string, unknown>;
      const ruleSetId = id("rules");
      const ruleSet = ruleDocumentRepository.createRuleSet({
        id: ruleSetId,
        projectId: params.projectId,
        name: String(input.name ?? "项目规则"),
        version: String(input.version ?? "v1"),
        scope: (input.scope as Record<string, unknown>) ?? {},
        content: String(input.content ?? ""),
        status: String(input.status ?? "active")
      });
      auditLog({ userId: actorId, projectId: params.projectId, action: "rules.create", resourceType: "rule_set", resourceId: ruleSetId, summary: String(input.name ?? "项目规则") });
      return ruleSet;
    }),
    route("GET", "/api/projects/:projectId/rule-documents", ({ params }) =>
      ruleDocumentRepository.listRuleDocuments(params.projectId)
    ),
    route("POST", "/api/projects/:projectId/rule-documents", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      const input = body as Record<string, unknown>;
      const ruleDocumentId = id("rule_doc");
      const document = ruleDocumentRepository.createRuleDocument({
        id: ruleDocumentId,
        projectId: params.projectId,
        name: String(input.name ?? "专家规则文档"),
        docType: String(input.doc_type ?? "markdown"),
        content: String(input.content ?? ""),
        version: String(input.version ?? "v1"),
        status: String(input.status ?? "active")
      });
      auditLog({ userId: actorId, projectId: params.projectId, action: "rule_documents.create", resourceType: "rule_document", resourceId: ruleDocumentId, summary: String(input.name ?? "专家规则文档") });
      return document;
    }),
    route("GET", "/api/projects/:projectId/expert-rule-bindings", ({ params }) =>
      ruleDocumentRepository.listExpertRuleBindings(params.projectId)
    ),
    route("POST", "/api/projects/:projectId/expert-rule-bindings", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      const input = body as Record<string, unknown>;
      const agentKey = String(input.agent_key ?? "");
      const ruleDocumentId = String(input.rule_document_id ?? "");
      if (!agentKey) return badRequest("agent_key is required");
      if (!ruleDocumentId) return badRequest("rule_document_id is required");
      const bindings = ruleDocumentRepository.bindRuleDocument({
        id: id("rule_binding"),
        projectId: params.projectId,
        agentKey,
        ruleDocumentId,
        priority: Number(input.priority ?? 100)
      });
      auditLog({ userId: actorId, projectId: params.projectId, action: "expert_rule_bindings.upsert", resourceType: "expert_rule_binding", resourceId: `${agentKey}:${ruleDocumentId}`, summary: `bind ${ruleDocumentId} to ${agentKey}` });
      return { items: bindings };
    }),
    route("GET", "/api/projects/:projectId/custom-skills", ({ params }) =>
      ruleDocumentRepository.listCustomSkills(params.projectId)
    ),
    route("POST", "/api/projects/:projectId/custom-skills", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      const input = body as Record<string, unknown>;
      const skillKey = normalizeSkillKey(String(input.skill_key ?? input.name ?? ""));
      if (!skillKey) return badRequest("skill_key or name is required");
      const content = String(input.content ?? "").trim();
      if (!content) return badRequest("content is required");
      const skill = ruleDocumentRepository.upsertCustomSkill({
        id: id("skill"),
        projectId: params.projectId,
        skillKey,
        name: String(input.name ?? skillKey),
        description: String(input.description ?? ""),
        content,
        version: String(input.version ?? "v1"),
        status: String(input.status ?? "active")
      });
      auditLog({ userId: actorId, projectId: params.projectId, action: "custom_skills.upsert", resourceType: "custom_skill", resourceId: skillKey, summary: `upsert custom skill ${skillKey}` });
      return skill;
    }),
    route("GET", "/api/projects/:projectId/expert-skill-bindings", ({ params }) =>
      ruleDocumentRepository.listExpertSkillBindings(params.projectId)
    ),
    route("POST", "/api/projects/:projectId/expert-skill-bindings", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      const input = body as Record<string, unknown>;
      const agentKey = String(input.agent_key ?? "");
      const skillKey = normalizeSkillKey(String(input.skill_key ?? ""));
      if (!agentKey) return badRequest("agent_key is required");
      if (!skillKey) return badRequest("skill_key is required");
      const bindings = ruleDocumentRepository.bindCustomSkill({
        id: id("skill_binding"),
        projectId: params.projectId,
        agentKey,
        skillKey,
        priority: Number(input.priority ?? 100),
        enabled: input.enabled === undefined ? true : Boolean(input.enabled)
      });
      auditLog({ userId: actorId, projectId: params.projectId, action: "expert_skill_bindings.upsert", resourceType: "expert_skill_binding", resourceId: `${agentKey}:${skillKey}`, summary: `bind ${skillKey} to ${agentKey}` });
      return { items: bindings };
    }),
    route("GET", "/api/projects/:projectId/custom-skill-assets", ({ params, url }) =>
      ruleDocumentRepository.listCustomSkillAssets(params.projectId, url.searchParams.get("skill_key") ?? undefined)
    ),
    route("POST", "/api/projects/:projectId/custom-skill-assets", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      const input = body as Record<string, unknown>;
      const skillKey = normalizeSkillKey(String(input.skill_key ?? ""));
      const assetPath = normalizeSkillAssetPath(String(input.asset_path ?? ""));
      const content = String(input.content ?? "");
      if (!skillKey) return badRequest("skill_key is required");
      if (!assetPath) return badRequest("asset_path is required");
      if (assetPath.includes("..")) return badRequest("asset_path cannot contain ..");
      if (!content.trim()) return badRequest("content is required");
      const assetType = inferSkillAssetType(assetPath, input.asset_type);
      const asset = ruleDocumentRepository.upsertCustomSkillAsset({
        id: id("skill_asset"),
        projectId: params.projectId,
        skillKey,
        assetPath,
        assetType,
        content,
        executable: Boolean(input.executable ?? assetType === "script")
      });
      auditLog({ userId: actorId, projectId: params.projectId, action: "custom_skill_assets.upsert", resourceType: "custom_skill_asset", resourceId: `${skillKey}:${assetPath}`, summary: `upsert custom skill asset ${skillKey}/${assetPath}` });
      return asset;
    }),
    route("GET", "/api/projects/:projectId/review-policy", ({ params }) =>
      ruleDocumentRepository.findReviewPolicy(params.projectId) ?? notFound()
    ),
    route("PATCH", "/api/projects/:projectId/review-policy", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      const input = body as Record<string, unknown>;
      const policy = ruleDocumentRepository.upsertReviewPolicy(params.projectId, (input.policy as Record<string, unknown>) ?? input);
      auditLog({ userId: actorId, projectId: params.projectId, action: "review_policy.update", resourceType: "review_policy", resourceId: `policy_${params.projectId}`, summary: "updated review policy" });
      return policy;
    }),
  ];
  return routes;
}
