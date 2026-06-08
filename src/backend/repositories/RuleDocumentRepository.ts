import type { Db } from "../db.js";

export class RuleDocumentRepository {
  constructor(private readonly db: Db) {}

  listRuleSets(projectId: string) {
    return this.db.prepare("SELECT * FROM rule_sets WHERE project_id = ? ORDER BY updated_at DESC").all(projectId);
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
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).run(input.id, input.projectId, input.name, input.version, JSON.stringify(input.scope), input.content, input.status);
    return this.db.prepare("SELECT * FROM rule_sets WHERE id = ?").get(input.id);
  }

  listRuleDocuments(projectId: string) {
    return this.db.prepare("SELECT * FROM rule_documents WHERE project_id = ? ORDER BY created_at DESC").all(projectId);
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
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).run(input.id, input.projectId, input.name, input.docType, input.content, input.version, input.status);
    return this.db.prepare("SELECT * FROM rule_documents WHERE id = ?").get(input.id);
  }

  listExpertRuleBindings(projectId: string) {
    return this.db.prepare(`
      SELECT erb.*, rd.name AS rule_document_name, rd.version, rd.status
      FROM expert_rule_bindings erb
      JOIN rule_documents rd ON rd.id = erb.rule_document_id
      WHERE erb.project_id = ?
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
    this.db.prepare(`
      INSERT INTO expert_rule_bindings (id, project_id, agent_key, rule_document_id, priority)
      VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(project_id, agent_key, rule_document_id) DO UPDATE SET
        priority = excluded.priority
    `).run(input.id, input.projectId, input.agentKey, input.ruleDocumentId, input.priority);
    return this.listExpertRuleBindings(input.projectId);
  }

  listCustomSkills(projectId: string) {
    return this.db.prepare(`
      SELECT *
      FROM custom_skills
      WHERE project_id = ?
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
    this.db.prepare(`
      INSERT INTO custom_skills (id, project_id, skill_key, name, description, content, version, status)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(project_id, skill_key) DO UPDATE SET
        name = excluded.name,
        description = excluded.description,
        content = excluded.content,
        version = excluded.version,
        status = excluded.status,
        updated_at = CURRENT_TIMESTAMP
    `).run(
      input.id,
      input.projectId,
      input.skillKey,
      input.name,
      input.description,
      input.content,
      input.version,
      input.status
    );
    return this.db.prepare("SELECT * FROM custom_skills WHERE project_id = ? AND skill_key = ?").get(input.projectId, input.skillKey);
  }

  listExpertSkillBindings(projectId: string) {
    return this.db.prepare(`
      SELECT esb.*, cs.name AS skill_name, cs.version, cs.status
      FROM expert_skill_bindings esb
      LEFT JOIN custom_skills cs
        ON cs.project_id = esb.project_id
       AND cs.skill_key = esb.skill_key
      WHERE esb.project_id = ?
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
      VALUES (?, ?, ?, ?, ?, ?)
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

  listCustomSkillAssets(projectId: string, skillKey?: string) {
    if (skillKey) {
      return this.db.prepare(`
        SELECT *
        FROM custom_skill_assets
        WHERE project_id = ? AND skill_key = ?
        ORDER BY asset_path
      `).all(projectId, skillKey);
    }
    return this.db.prepare(`
      SELECT *
      FROM custom_skill_assets
      WHERE project_id = ?
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
  }) {
    this.db.prepare(`
      INSERT INTO custom_skill_assets (
        id, project_id, skill_key, asset_path, asset_type, content, executable
      )
      VALUES (?, ?, ?, ?, ?, ?, ?)
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
    return this.db.prepare(`
      SELECT *
      FROM custom_skill_assets
      WHERE project_id = ? AND skill_key = ? AND asset_path = ?
    `).get(input.projectId, input.skillKey, input.assetPath);
  }

  findReviewPolicy(projectId: string) {
    return this.db.prepare("SELECT * FROM review_policy WHERE project_id = ?").get(projectId);
  }

  upsertReviewPolicy(projectId: string, policy: Record<string, unknown>) {
    this.db.prepare(`
      INSERT INTO review_policy (id, project_id, policy_json)
      VALUES (?, ?, ?)
      ON CONFLICT(project_id) DO UPDATE SET policy_json = excluded.policy_json, updated_at = CURRENT_TIMESTAMP
    `).run(`policy_${projectId}`, projectId, JSON.stringify(policy));
    return this.findReviewPolicy(projectId);
  }
}
