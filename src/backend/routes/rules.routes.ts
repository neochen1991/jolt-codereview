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

type ParsedRuleDetail = {
  rule_id: string;
  title: string;
  document_name: string;
  version: string;
  sections: Record<string, string>;
  raw_excerpt: string;
};

const RULE_HEADING_RE = /^##\s+([A-Za-z0-9_-]+(?::[A-Za-z0-9_-]+)?)\s+(.+)$/;
const RULE_SECTION_RE = /^###\s+(.+)$/;

function requestedRuleIds(url: URL) {
  const values = [
    ...url.searchParams.getAll("rule_id"),
    ...url.searchParams.getAll("rule_ids")
  ];
  return [...new Set(
    values
      .flatMap((value) => value.split(","))
      .map((value) => value.trim())
      .filter(Boolean)
  )].slice(0, 50);
}

function parseRuleDetailsFromDocument(document: { name?: string; version?: string; content?: string }, wanted: Set<string>) {
  const details = new Map<string, ParsedRuleDetail>();
  const lines = String(document.content || "").split(/\r?\n/);
  let current: { ruleId: string; title: string; body: string[] } | null = null;

  function flush() {
    if (!current) return;
    if (wanted.has(current.ruleId)) {
      const sections: Record<string, string> = {};
      let sectionName = "说明";
      const rawExcerpt: string[] = [];
      for (const line of current.body) {
        rawExcerpt.push(line);
        const section = line.trim().match(RULE_SECTION_RE);
        if (section) {
          sectionName = section[1].trim();
          sections[sectionName] = "";
          continue;
        }
        if (!line.trim()) continue;
        sections[sectionName] = [sections[sectionName], line.trim()].filter(Boolean).join("\n");
      }
      details.set(current.ruleId, {
        rule_id: current.ruleId,
        title: current.title,
        document_name: String(document.name || "规则文档"),
        version: String(document.version || "v1"),
        sections,
        raw_excerpt: rawExcerpt.join("\n").trim().slice(0, 4000)
      });
    }
    current = null;
  }

  for (const line of lines) {
    const heading = line.trim().match(RULE_HEADING_RE);
    if (heading) {
      flush();
      current = { ruleId: heading[1], title: heading[2].trim(), body: [] };
      continue;
    }
    if (current) current.body.push(line);
  }
  flush();
  return details;
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
    route("GET", "/api/projects/:projectId/rule-sets", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return ruleDocumentRepository.listRuleSets(params.projectId);
    }),
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
    route("GET", "/api/projects/:projectId/rule-documents", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return ruleDocumentRepository.listRuleDocuments(params.projectId);
    }),
    route("GET", "/api/projects/:projectId/rule-details", ({ params, url, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      const ruleIds = requestedRuleIds(url);
      if (!ruleIds.length) return { items: [] };
      const wanted = new Set(ruleIds);
      const documents = all<{ project_id: string; name: string; version: string; content: string }>(
        `
        SELECT project_id, name, version, content
        FROM rule_documents
        WHERE status = 'active'
          AND project_id IN (?, 'project_default')
        ORDER BY CASE WHEN project_id = ? THEN 0 ELSE 1 END, created_at DESC
        `,
        [params.projectId, params.projectId]
      );
      const found = new Map<string, ParsedRuleDetail>();
      for (const document of documents) {
        const parsed = parseRuleDetailsFromDocument(document, wanted);
        for (const [ruleId, detail] of parsed) {
          if (!found.has(ruleId)) found.set(ruleId, detail);
        }
      }
      return {
        items: ruleIds.map((ruleId) => found.get(ruleId) ?? {
          rule_id: ruleId,
          title: ruleId,
          document_name: "",
          version: "",
          sections: {},
          raw_excerpt: "",
          missing: true
        })
      };
    }),
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
    route("GET", "/api/projects/:projectId/expert-rule-bindings", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return ruleDocumentRepository.listExpertRuleBindings(params.projectId);
    }),
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
    route("GET", "/api/projects/:projectId/custom-skills", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return ruleDocumentRepository.listCustomSkills(params.projectId);
    }),
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
    route("GET", "/api/projects/:projectId/expert-skill-bindings", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return ruleDocumentRepository.listExpertSkillBindings(params.projectId);
    }),
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
    route("GET", "/api/projects/:projectId/custom-skill-assets", ({ params, url, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return ruleDocumentRepository.listCustomSkillAssets(params.projectId, url.searchParams.get("skill_key") ?? undefined);
    }),
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
    route("GET", "/api/projects/:projectId/review-policy", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return ruleDocumentRepository.findReviewPolicy(params.projectId) ?? notFound();
    }),
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
