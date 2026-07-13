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
  const normalized = value
    .trim()
    .replace(/\\/g, "/")
    .replace(/^\/+/, "")
    .replace(/\/+/g, "/")
    .slice(0, 180);
  const [head, ...tail] = normalized.split("/").filter(Boolean);
  const lowerHead = String(head || "").toLowerCase();
  if (lowerHead === "skill.md") return "SKILL.md";
  if (lowerHead === "references") return ["references", ...tail].join("/");
  if (lowerHead === "scripts") return ["scripts", ...tail].join("/");
  if (lowerHead === "assets") return ["assets", ...tail].join("/");
  return normalized;
}

function inferSkillAssetType(path: string, explicit?: unknown) {
  if (typeof explicit === "string" && explicit.trim()) return explicit.trim();
  if (path === "SKILL.md") return "skill";
  if (path.startsWith("references/")) return "reference";
  if (path.startsWith("scripts/")) return "script";
  if (path.startsWith("assets/")) return "asset";
  return "reference";
}

type SkillAssetInput = {
  skill_key?: string;
  asset_path: string;
  asset_type?: string;
  content: string;
};

const SKILL_FRONTMATTER_RE = /^---\r?\n([\s\S]*?)\r?\n---/;
const SKILL_CHECKPOINT_HEADING_RE = /^##\s+(?:checkpoint[:：]\s*)?([A-Za-z][A-Za-z0-9_.:-]*-[A-Za-z0-9_.:-]+|[A-Z]{2,}[A-Z0-9_-]*-\d+[A-Z0-9_-]*)\s+(.+)$/i;
const SKILL_FIELD_RE = /^-\s*([a-zA-Z_]+):\s*(.*)$/;
const SKILL_SECTION_RE = /^###\s+(.+)$/;
const SUSPICIOUS_FIELD_BULLET_RE = /^-\s*([a-zA-Z0-9_.-]+:[a-zA-Z0-9_.:-]+)\s+(.+)$/;

function parseFrontmatter(content: string) {
  const match = content.match(SKILL_FRONTMATTER_RE);
  if (!match) return {};
  return Object.fromEntries(
    match[1]
      .split(/\r?\n/)
      .map((line) => line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/))
      .filter((match): match is RegExpMatchArray => Boolean(match))
      .map((match) => [match[1], match[2].replace(/^["']|["']$/g, "").trim()])
  );
}

function compactSkillText(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function extractSkillSections(lines: string[]) {
  const sections: Record<string, string[]> = {};
  let current = "";
  for (const raw of lines) {
    const line = raw.trim();
    const section = line.match(SKILL_SECTION_RE);
    if (section) {
      current = section[1].trim();
      sections[current] = sections[current] || [];
      continue;
    }
    if (current && line) sections[current].push(line);
  }
  return sections;
}

function joinSkillSections(sections: Record<string, string[]>, names: string[]) {
  const lowered = new Map(Object.keys(sections).map((key) => [key.toLowerCase(), key]));
  return names
    .map((name) => {
      const key = lowered.get(name.toLowerCase()) || name;
      const values = sections[key] || [];
      return values.length ? `${key}：${values.join(" ")}` : "";
    })
    .filter(Boolean)
    .join("\n");
}

function parseSkillCheckpoints(skillKey: string, content: string, sourcePath: string) {
  const checkpoints: Array<Record<string, string>> = [];
  let current: Record<string, string | string[]> | null = null;
  const flush = () => {
    if (!current) return;
    const body = Array.isArray(current.body) ? current.body : [];
    const sections = extractSkillSections(body);
    const check = String(current.check || "").trim() || joinSkillSections(sections, ["检查点", "如何检查", "规范说明", "规则说明"]);
    if (!check.trim()) {
      current = null;
      return;
    }
    const requiredEvidence = String(current.required_evidence || current.evidence_required || "").trim()
      || joinSkillSections(sections, ["证据要求", "输出要求", "Required Evidence"]);
    const falsePositivePatterns = String(current.false_positive_patterns || "").trim()
      || joinSkillSections(sections, ["误报模式", "误报排除", "例外"]);
    const fixGuidance = String(current.fix_guidance || "").trim()
      || joinSkillSections(sections, ["修复建议", "整改建议"]);
    checkpoints.push({
      skill_key: skillKey,
      checkpoint_id: String(current.checkpoint_id || ""),
      rule_id: String(current.checkpoint_id || ""),
      title: String(current.title || ""),
      severity: String(current.severity || "medium"),
      applies_to: String(current.applies_to || "**/*"),
      check: compactSkillText(check),
      required_evidence: compactSkillText(requiredEvidence || "精确文件、行号、源码证据和触发条件。"),
      false_positive_patterns: compactSkillText(falsePositivePatterns),
      fix_guidance: compactSkillText(fixGuidance),
      source_path: sourcePath,
      parse_quality: "structured"
    });
    current = null;
  };
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trimEnd();
    const heading = line.match(SKILL_CHECKPOINT_HEADING_RE);
    if (heading) {
      flush();
      current = {
        checkpoint_id: heading[1].trim(),
        title: heading[2].trim(),
        severity: "medium",
        applies_to: "**/*",
        check: "",
        required_evidence: "",
        false_positive_patterns: "",
        fix_guidance: "",
        body: []
      };
      continue;
    }
    if (!current) continue;
    const field = line.trim().match(SKILL_FIELD_RE);
    if (field) {
      current[field[1].trim()] = field[2].trim();
      continue;
    }
    (current.body as string[]).push(line);
  }
  flush();
  return checkpoints;
}

function validateSkillBundlePayload(raw: Record<string, unknown>) {
  const skillKey = normalizeSkillKey(String(raw.skill_key || raw.name || "uploaded-skill")) || "uploaded-skill";
  const rawAssets = Array.isArray(raw.assets) ? raw.assets : [];
  const assets = rawAssets
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object" && !Array.isArray(item)))
    .map((item): SkillAssetInput => ({
      skill_key: skillKey,
      asset_path: normalizeSkillAssetPath(String(item.asset_path || item.path || "")),
      asset_type: inferSkillAssetType(normalizeSkillAssetPath(String(item.asset_path || item.path || "")), item.asset_type),
      content: String(item.content || "")
    }))
    .filter((item) => item.asset_path && item.content.trim());
  if (!assets.some((asset) => asset.asset_path === "SKILL.md") && String(raw.content || "").trim()) {
    assets.unshift({ skill_key: skillKey, asset_path: "SKILL.md", asset_type: "skill", content: String(raw.content || "") });
  }
  const failures: Array<Record<string, unknown>> = [];
  const warnings: Array<Record<string, unknown>> = [];
  if (!assets.length) failures.push({ path: "", message: "no skill assets provided" });
  const skillMd = assets.find((asset) => asset.asset_path === "SKILL.md");
  if (!skillMd) {
    failures.push({ path: "SKILL.md", message: "missing SKILL.md" });
  } else {
    const frontmatter = parseFrontmatter(skillMd.content);
    for (const field of ["name", "description"]) {
      if (!String(frontmatter[field] || "").trim()) failures.push({ path: "SKILL.md", message: `missing frontmatter field: ${field}` });
    }
  }
  const checkpoints: Array<Record<string, string>> = [];
  const sources = assets.filter((asset) => asset.asset_path === "SKILL.md" || (asset.asset_path.startsWith("references/") && /\.(md|mdx|txt)$/i.test(asset.asset_path)));
  for (const asset of sources) {
    checkpoints.push(...parseSkillCheckpoints(skillKey, asset.content, asset.asset_path));
    for (const [index, line] of asset.content.split(/\r?\n/).entries()) {
      const suspicious = line.trim().match(SUSPICIOUS_FIELD_BULLET_RE);
      if (suspicious) {
        warnings.push({
          path: asset.asset_path,
          line: index + 1,
          message: `suspicious field-like bullet may be parsed incorrectly: ${suspicious[1]}`,
        });
      }
    }
  }
  const checkpointIds = new Map<string, string>();
  for (const checkpoint of checkpoints) {
    const checkpointId = checkpoint.checkpoint_id;
    if (checkpointIds.has(checkpointId)) {
      failures.push({ path: checkpoint.source_path, message: `duplicate checkpoint_id: ${checkpointId}` });
    }
    checkpointIds.set(checkpointId, checkpoint.source_path);
    for (const field of ["required_evidence", "false_positive_patterns", "fix_guidance"]) {
      if (!String(checkpoint[field] || "").trim()) {
        failures.push({ path: checkpoint.source_path, checkpoint_id: checkpointId, message: `checkpoint missing ${field}` });
      }
    }
  }
  if (!checkpoints.length) failures.push({ path: "", message: "no structured checkpoints parsed from SKILL.md or references" });
  return {
    ok: failures.length === 0,
    skill_key: skillKey,
    asset_count: assets.length,
    failures,
    warnings,
    checkpoints
  };
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
          AND project_id IN ($1, 'project_default')
        ORDER BY CASE WHEN project_id = $2 THEN 0 ELSE 1 END, created_at DESC
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
      let bindings;
      try {
        bindings = ruleDocumentRepository.bindRuleDocument({
          id: id("rule_binding"),
          projectId: params.projectId,
          agentKey,
          ruleDocumentId,
          priority: Number(input.priority ?? 100)
        });
      } catch (error) {
        return badRequest((error as Error).message);
      }
      auditLog({ userId: actorId, projectId: params.projectId, action: "expert_rule_bindings.upsert", resourceType: "expert_rule_binding", resourceId: `${agentKey}:${ruleDocumentId}`, summary: `bind ${ruleDocumentId} to ${agentKey}` });
      return { items: bindings };
    }),
    route("DELETE", "/api/projects/:projectId/expert-rule-bindings/:bindingId", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      const result = ruleDocumentRepository.deleteExpertRuleBinding(params.projectId, params.bindingId);
      auditLog({ userId: actorId, projectId: params.projectId, action: "expert_rule_bindings.delete", resourceType: "expert_rule_binding", resourceId: params.bindingId, summary: "delete expert rule binding" });
      return { deleted: result.changes };
    }),
    route("GET", "/api/projects/:projectId/custom-skills", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return ruleDocumentRepository.listCustomSkills(params.projectId);
    }),
    route("GET", "/api/projects/:projectId/custom-skills/:skillKey/versions", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return ruleDocumentRepository.listCustomSkillVersions(params.projectId, params.skillKey);
    }),
    route("POST", "/api/projects/:projectId/custom-skills/validate", ({ params, body, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      return validateSkillBundlePayload((body as Record<string, unknown>) || {});
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
      const validation = validateSkillBundlePayload({ ...input, assets: [{ asset_path: "SKILL.md", asset_type: "skill", content }] });
      if (input.enforce_validation === true && !validation.ok) {
        return { statusCode: 400, error: "invalid_skill_bundle", message: "Skill validation failed", validation };
      }
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
    route("POST", "/api/projects/:projectId/custom-skills/:skillKey/versions/:version/activate", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectRole(params.projectId, actorId, "project_admin");
      if (denied) return denied;
      const activated = ruleDocumentRepository.activateCustomSkillVersion(params.projectId, params.skillKey, params.version);
      if (!activated) return notFound();
      auditLog({
        userId: actorId,
        projectId: params.projectId,
        action: "custom_skills.activate_version",
        resourceType: "custom_skill",
        resourceId: `${params.skillKey}:${params.version}`,
        summary: `activate ${params.skillKey} ${params.version}`
      });
      return activated;
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
    route("DELETE", "/api/projects/:projectId/expert-skill-bindings/:bindingId", ({ params, req }) => {
      const actorId = currentUserId(req);
      const denied = ensureProjectWrite(params.projectId, actorId);
      if (denied) return denied;
      const result = ruleDocumentRepository.deleteExpertSkillBinding(params.projectId, params.bindingId);
      auditLog({ userId: actorId, projectId: params.projectId, action: "expert_skill_bindings.delete", resourceType: "expert_skill_binding", resourceId: params.bindingId, summary: "delete expert skill binding" });
      return { deleted: result.changes };
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
      const hasSuspiciousFieldBullet = content.split(/\r?\n/).some((line) => SUSPICIOUS_FIELD_BULLET_RE.test(line.trim()));
      if ((assetPath === "SKILL.md" || (assetPath.startsWith("references/") && /\.(md|mdx|txt)$/i.test(assetPath))) && hasSuspiciousFieldBullet) {
        return {
          statusCode: 400,
          error: "invalid_skill_asset",
          message: "Skill asset contains field-like bullet syntax; move it under a section sentence, for example '永久配置 key，例如 system:refund:config'.",
        };
      }
      const version = String(input.version || "").trim();
      if (version) {
        try {
          const versioned = ruleDocumentRepository.upsertCustomSkillVersionAsset({
            projectId: params.projectId,
            skillKey,
            version,
            assetPath,
            assetType,
            content,
            executable: Boolean(input.executable ?? assetType === "script")
          });
          if (!versioned) return notFound();
          auditLog({ userId: actorId, projectId: params.projectId, action: "custom_skill_versions.asset_upsert", resourceType: "custom_skill_version", resourceId: `${skillKey}:${version}:${assetPath}`, summary: `upsert draft skill asset ${skillKey}/${assetPath}` });
          return versioned;
        } catch (error) {
          return badRequest((error as Error).message);
        }
      }
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
