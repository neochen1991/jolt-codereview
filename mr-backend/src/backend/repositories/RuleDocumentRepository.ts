import { createHash } from "node:crypto";
import type { Db } from "../db.js";

function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export function canonicalSkillBundleHash(skill: Record<string, any>) {
  let assets: unknown = skill.assets_json || [];
  if (typeof assets === "string") {
    try { assets = JSON.parse(assets); } catch { assets = []; }
  }
  const normalizedAssets = (Array.isArray(assets) ? assets : [])
    .filter((item) => item && typeof item === "object")
    .map((item: Record<string, any>) => ({
      skill_key: String(item.skill_key || skill.skill_key || ""),
      asset_path: String(item.asset_path || ""),
      asset_type: String(item.asset_type || "reference"),
      content: String(item.content || ""),
      executable: Boolean(item.executable)
    }))
    .sort((left, right) => left.asset_path.localeCompare(right.asset_path));
  return createHash("sha256").update(stableStringify({
    skill_key: String(skill.skill_key || ""),
    version: String(skill.version || ""),
    name: String(skill.name || ""),
    description: String(skill.description || ""),
    content: String(skill.content || ""),
    assets: normalizedAssets
  })).digest("hex");
}

export function resolveCanonicalSkillVersion(db: Db, projectId: string, skillKey: string, version?: string | null) {
  if (version) {
    return db.prepare(`
      SELECT * FROM custom_skill_versions
      WHERE project_id = $1 AND skill_key = $2 AND version = $3
    `).get(projectId, skillKey, version) as Record<string, any> | undefined;
  }
  return db.prepare(`
    SELECT csv.* FROM custom_skills cs
    JOIN custom_skill_versions csv ON csv.id = cs.active_version_id
    WHERE cs.project_id = $1 AND cs.skill_key = $2 AND cs.status = 'active'
  `).get(projectId, skillKey) as Record<string, any> | undefined;
}

export class RuleDocumentRepository {
  constructor(private readonly db: Db) {}

  listRuleSets(projectId: string) {
    return this.db.prepare("SELECT * FROM rule_sets WHERE project_id = $1 ORDER BY updated_at DESC").all(projectId);
  }

  createRuleSet(input: {
    id: string;
    projectId: string;
    name: string;
    version: string;
    scope: Record<string, unknown>;
    content: string;
    status: string;
  }) {
    this.db.prepare(`
      INSERT INTO rule_sets (id, project_id, name, version, scope_json, content, status)
      VALUES ($1, $2, $3, $4, $5, $6, $7)
    `).run(input.id, input.projectId, input.name, input.version, JSON.stringify(input.scope), input.content, input.status);
    return this.db.prepare("SELECT * FROM rule_sets WHERE id = $1").get(input.id);
  }

  listRuleDocuments(projectId: string) {
    return this.db.prepare("SELECT * FROM rule_documents WHERE project_id = $1 ORDER BY created_at DESC").all(projectId);
  }

  createRuleDocument(input: {
    id: string;
    projectId: string;
    name: string;
    docType: string;
    content: string;
    version: string;
    status: string;
  }) {
    this.db.prepare(`
      INSERT INTO rule_documents (id, project_id, name, doc_type, content, version, status)
      VALUES ($1, $2, $3, $4, $5, $6, $7)
    `).run(input.id, input.projectId, input.name, input.docType, input.content, input.version, input.status);
    return this.db.prepare("SELECT * FROM rule_documents WHERE id = $1").get(input.id);
  }

  listExpertRuleBindings(projectId: string) {
    return this.db.prepare(`
      SELECT erb.*, rd.name AS rule_document_name, rd.version, rd.status
      FROM expert_rule_bindings erb
      JOIN rule_documents rd ON rd.id = erb.rule_document_id AND rd.project_id = erb.project_id
      WHERE erb.project_id = $1
      ORDER BY erb.agent_key, erb.priority, rd.name
    `).all(projectId);
  }

  bindRuleDocument(input: {
    id: string;
    projectId: string;
    agentKey: string;
    ruleDocumentId: string;
    priority: number;
  }) {
    const document = this.db.prepare("SELECT id FROM rule_documents WHERE id = $1 AND project_id = $2")
      .get(input.ruleDocumentId, input.projectId);
    if (!document) {
      throw new Error("rule_document_id must belong to project");
    }
    this.db.prepare(`
      INSERT INTO expert_rule_bindings (id, project_id, agent_key, rule_document_id, priority)
      VALUES ($1, $2, $3, $4, $5)
      ON CONFLICT(project_id, agent_key, rule_document_id) DO UPDATE SET
        priority = excluded.priority
    `).run(input.id, input.projectId, input.agentKey, input.ruleDocumentId, input.priority);
    return this.listExpertRuleBindings(input.projectId);
  }

  deleteExpertRuleBinding(projectId: string, bindingId: string) {
    return this.db.prepare("DELETE FROM expert_rule_bindings WHERE project_id = $1 AND id = $2").run(projectId, bindingId);
  }

  listCustomSkills(projectId: string) {
    return this.db.prepare(`
      SELECT * FROM custom_skills WHERE project_id = $1
      UNION ALL
      SELECT csv.id, csv.project_id, csv.skill_key, csv.name, csv.description, csv.content,
             csv.version, csv.status, csv.created_at, csv.updated_at
      FROM custom_skill_versions csv
      WHERE csv.project_id = $1
        AND NOT EXISTS (
          SELECT 1 FROM custom_skills cs
          WHERE cs.project_id = csv.project_id AND cs.skill_key = csv.skill_key
        )
        AND csv.updated_at = (
          SELECT MAX(latest.updated_at) FROM custom_skill_versions latest
          WHERE latest.project_id = csv.project_id AND latest.skill_key = csv.skill_key
        )
      ORDER BY updated_at DESC, name
    `).all(projectId);
  }

  upsertCustomSkill(input: {
    id: string;
    projectId: string;
    skillKey: string;
    name: string;
    description: string;
    content: string;
    version: string;
    status: string;
  }) {
    if (input.status === "active") {
      this.db.prepare(`
        INSERT INTO custom_skills (id, project_id, skill_key, name, description, content, version, status)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT(project_id, skill_key) DO UPDATE SET
          name = excluded.name,
          description = excluded.description,
          content = excluded.content,
          version = excluded.version,
          status = excluded.status,
          updated_at = CURRENT_TIMESTAMP
      `).run(
        input.id, input.projectId, input.skillKey, input.name, input.description,
        input.content, input.version, input.status
      );
    }
    this.db.prepare(`
      INSERT INTO custom_skill_versions (
        id, project_id, skill_key, version, name, description, content, assets_json, status
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
      ON CONFLICT(project_id, skill_key, version) DO UPDATE SET
        name = excluded.name,
        description = excluded.description,
        content = excluded.content,
        assets_json = excluded.assets_json,
        status = excluded.status,
        updated_at = CURRENT_TIMESTAMP
      WHERE custom_skill_versions.status <> 'active'
    `).run(
      `skill_version_${input.id}`,
      input.projectId,
      input.skillKey,
      input.version,
      input.name,
      input.description,
      input.content,
      JSON.stringify(input.status === "active" ? this.listCustomSkillAssets(input.projectId, input.skillKey) : []),
      input.status
    );
    this.refreshCustomSkillVersionHash(input.projectId, input.skillKey, input.version);
    return this.findCustomSkillVersion(input.projectId, input.skillKey, input.version);
  }

  listCustomSkillVersions(projectId: string, skillKey: string) {
    return this.db.prepare(`
      SELECT * FROM custom_skill_versions
      WHERE project_id = $1 AND skill_key = $2
      ORDER BY created_at DESC
    `).all(projectId, skillKey);
  }

  findCustomSkillVersion(projectId: string, skillKey: string, version?: string | null) {
    if (version) {
      return this.db.prepare(`
        SELECT * FROM custom_skill_versions
        WHERE project_id = $1 AND skill_key = $2 AND version = $3
      `).get(projectId, skillKey, version);
    }
    return this.db.prepare(`
      SELECT * FROM custom_skill_versions
      WHERE project_id = $1 AND skill_key = $2
      ORDER BY updated_at DESC LIMIT 1
    `).get(projectId, skillKey);
  }

  upsertCustomSkillVersionAsset(input: {
    projectId: string;
    skillKey: string;
    version: string;
    assetPath: string;
    assetType: string;
    content: string;
    executable: boolean;
  }) {
    const selected = this.findCustomSkillVersion(input.projectId, input.skillKey, input.version) as Record<string, any> | undefined;
    if (!selected) return undefined;
    if (selected.status === "active") throw new Error("active Skill versions are immutable");
    const assets = JSON.parse(String(selected.assets_json || "[]")) as Array<Record<string, any>>;
    const next = assets.filter((asset) => String(asset.asset_path) !== input.assetPath);
    next.push({
      skill_key: input.skillKey,
      asset_path: input.assetPath,
      asset_type: input.assetType,
      content: input.content,
      executable: input.executable ? 1 : 0
    });
    next.sort((left, right) => String(left.asset_path).localeCompare(String(right.asset_path)));
    this.db.prepare(`
      UPDATE custom_skill_versions SET assets_json = $1, updated_at = CURRENT_TIMESTAMP
      WHERE project_id = $2 AND skill_key = $3 AND version = $4
    `).run(JSON.stringify(next), input.projectId, input.skillKey, input.version);
    this.refreshCustomSkillVersionHash(input.projectId, input.skillKey, input.version);
    return this.findCustomSkillVersion(input.projectId, input.skillKey, input.version);
  }

  refreshCustomSkillVersionHash(projectId: string, skillKey: string, version: string) {
    const selected = this.findCustomSkillVersion(projectId, skillKey, version) as Record<string, any> | undefined;
    if (!selected) return undefined;
    const bundleSha256 = canonicalSkillBundleHash(selected);
    this.db.prepare("UPDATE custom_skill_versions SET bundle_sha256 = $1 WHERE id = $2").run(bundleSha256, selected.id);
    return bundleSha256;
  }

  activateCustomSkillVersion(projectId: string, skillKey: string, version: string) {
    const selected = this.findCustomSkillVersion(projectId, skillKey, version) as Record<string, any> | undefined;
    if (!selected) return undefined;
    const assets = JSON.parse(String(selected.assets_json || "[]")) as Array<Record<string, any>>;
    this.refreshCustomSkillVersionHash(projectId, skillKey, version);
    this.db.prepare(`
      UPDATE custom_skill_versions
      SET status = CASE WHEN version = $1 THEN 'active' WHEN status = 'active' THEN 'reviewed' ELSE status END,
          updated_at = CURRENT_TIMESTAMP
      WHERE project_id = $2 AND skill_key = $3
    `).run(version, projectId, skillKey);
    this.db.prepare(`
      INSERT INTO custom_skills (id, project_id, skill_key, name, description, content, version, status, active_version_id)
      VALUES ($1, $2, $3, $4, $5, $6, $7, 'active', $8)
      ON CONFLICT(project_id, skill_key) DO UPDATE SET
        name = excluded.name, description = excluded.description, content = excluded.content,
        version = excluded.version, status = 'active', active_version_id = excluded.active_version_id, updated_at = CURRENT_TIMESTAMP
    `).run(String(selected.id), projectId, skillKey, selected.name, selected.description, selected.content, version, selected.id);
    this.db.prepare("DELETE FROM custom_skill_assets WHERE project_id = $1 AND skill_key = $2").run(projectId, skillKey);
    for (const asset of assets) {
      this.upsertCustomSkillAsset({
        id: String(asset.id || `skill_asset_${skillKey}_${asset.asset_path}`),
        projectId,
        skillKey,
        assetPath: String(asset.asset_path),
        assetType: String(asset.asset_type || "reference"),
        content: String(asset.content || ""),
        executable: Boolean(asset.executable)
      }, false);
    }
    return this.findCustomSkillVersion(projectId, skillKey, version);
  }

  listExpertSkillBindings(projectId: string) {
    return this.db.prepare(`
      SELECT esb.*, cs.name AS skill_name, cs.version, cs.status
      FROM expert_skill_bindings esb
      LEFT JOIN custom_skills cs
        ON cs.project_id = esb.project_id
       AND cs.skill_key = esb.skill_key
      WHERE esb.project_id = $1
      ORDER BY esb.agent_key, esb.priority, esb.skill_key
    `).all(projectId);
  }

  bindCustomSkill(input: {
    id: string;
    projectId: string;
    agentKey: string;
    skillKey: string;
    priority: number;
    enabled: boolean;
  }) {
    this.db.prepare(`
      INSERT INTO expert_skill_bindings (id, project_id, agent_key, skill_key, priority, enabled)
      VALUES ($1, $2, $3, $4, $5, $6)
      ON CONFLICT(project_id, agent_key, skill_key) DO UPDATE SET
        priority = excluded.priority,
        enabled = excluded.enabled
    `).run(
      input.id,
      input.projectId,
      input.agentKey,
      input.skillKey,
      input.priority,
      input.enabled ? 1 : 0
    );
    return this.listExpertSkillBindings(input.projectId);
  }

  deleteExpertSkillBinding(projectId: string, bindingId: string) {
    return this.db.prepare("DELETE FROM expert_skill_bindings WHERE project_id = $1 AND id = $2").run(projectId, bindingId);
  }

  listCustomSkillAssets(projectId: string, skillKey?: string) {
    if (skillKey) {
      return this.db.prepare(`
        SELECT *
        FROM custom_skill_assets
        WHERE project_id = $1 AND skill_key = $2
        ORDER BY asset_path
      `).all(projectId, skillKey);
    }
    return this.db.prepare(`
      SELECT *
      FROM custom_skill_assets
      WHERE project_id = $1
      ORDER BY skill_key, asset_path
    `).all(projectId);
  }

  upsertCustomSkillAsset(input: {
    id: string;
    projectId: string;
    skillKey: string;
    assetPath: string;
    assetType: string;
    content: string;
    executable: boolean;
  }, syncVersion = true) {
    this.db.prepare(`
      INSERT INTO custom_skill_assets (
        id, project_id, skill_key, asset_path, asset_type, content, executable
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7)
      ON CONFLICT(project_id, skill_key, asset_path) DO UPDATE SET
        asset_type = excluded.asset_type,
        content = excluded.content,
        executable = excluded.executable,
        updated_at = CURRENT_TIMESTAMP
    `).run(
      input.id,
      input.projectId,
      input.skillKey,
      input.assetPath,
      input.assetType,
      input.content,
      input.executable ? 1 : 0
    );
    if (syncVersion) this.syncCurrentSkillVersionAssets(input.projectId, input.skillKey);
    return this.db.prepare(`
      SELECT *
      FROM custom_skill_assets
      WHERE project_id = $1 AND skill_key = $2 AND asset_path = $3
    `).get(input.projectId, input.skillKey, input.assetPath);
  }

  private syncCurrentSkillVersionAssets(projectId: string, skillKey: string) {
    const skill = this.db.prepare("SELECT version FROM custom_skills WHERE project_id = $1 AND skill_key = $2")
      .get(projectId, skillKey) as { version?: string } | undefined;
    if (!skill?.version) return;
    this.db.prepare(`
      UPDATE custom_skill_versions
      SET assets_json = $1, updated_at = CURRENT_TIMESTAMP
      WHERE project_id = $2 AND skill_key = $3 AND version = $4 AND status <> 'active'
    `).run(JSON.stringify(this.listCustomSkillAssets(projectId, skillKey)), projectId, skillKey, skill.version);
  }

  findReviewPolicy(projectId: string) {
    return this.db.prepare("SELECT * FROM review_policy WHERE project_id = $1").get(projectId);
  }

  upsertReviewPolicy(projectId: string, policy: Record<string, unknown>) {
    this.db.prepare(`
      INSERT INTO review_policy (id, project_id, policy_json)
      VALUES ($1, $2, $3)
      ON CONFLICT(project_id) DO UPDATE SET policy_json = excluded.policy_json, updated_at = CURRENT_TIMESTAMP
    `).run(`policy_${projectId}`, projectId, JSON.stringify(policy));
    return this.findReviewPolicy(projectId);
  }
}
