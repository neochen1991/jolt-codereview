import type { Db } from "../db.js";

export class ProjectRepository {
  constructor(private readonly db: Db) {}

  ensureReviewDefaults(targetProjectId: string, sourceProjectId = "project_default") {
    const existing = this.db.prepare("SELECT 1 FROM review_policy WHERE project_id = $1 LIMIT 1").get(targetProjectId);
    if (existing) return;
    this.cloneReviewDefaults(sourceProjectId, targetProjectId);
  }

  private cloneReviewDefaults(sourceProjectId: string, targetProjectId: string) {
    const suffix = targetProjectId.replace(/[^a-zA-Z0-9]+/g, "_");
    this.db.prepare(`
      INSERT INTO review_policy (id, project_id, policy_json)
      SELECT $1, $2, policy_json
      FROM review_policy
      WHERE project_id = $3
      ON CONFLICT DO NOTHING
    `).run(`policy_${suffix}`, targetProjectId, sourceProjectId);
    this.db.prepare(`
      INSERT INTO rule_sets (id, project_id, name, version, scope_json, content, status)
      SELECT 'rules_' || substr(md5(random()::text || clock_timestamp()::text), 1, 16), $1, name, version, scope_json, content, status
      FROM rule_sets
      WHERE project_id = $2
      ON CONFLICT DO NOTHING
    `).run(targetProjectId, sourceProjectId);
    this.db.prepare(`
      INSERT INTO rule_documents (id, project_id, name, doc_type, content, version, status)
      SELECT 'rule_doc_' || substr(md5(random()::text || clock_timestamp()::text), 1, 16), $1, name, doc_type, content, version, status
      FROM rule_documents
      WHERE project_id = $2
      ON CONFLICT DO NOTHING
    `).run(targetProjectId, sourceProjectId);
    this.db.prepare(`
      INSERT INTO custom_skills (id, project_id, skill_key, name, description, content, version, status)
      SELECT 'skill_' || substr(md5(random()::text || clock_timestamp()::text), 1, 16), $1, skill_key, name, description, content, version, status
      FROM custom_skills
      WHERE project_id = $2
      ON CONFLICT DO NOTHING
    `).run(targetProjectId, sourceProjectId);
    this.db.prepare(`
      INSERT INTO custom_skill_assets (id, project_id, skill_key, asset_path, asset_type, content, executable)
      SELECT 'skill_asset_' || substr(md5(random()::text || clock_timestamp()::text), 1, 16), $1, skill_key, asset_path, asset_type, content, executable
      FROM custom_skill_assets
      WHERE project_id = $2
      ON CONFLICT DO NOTHING
    `).run(targetProjectId, sourceProjectId);
    this.db.prepare(`
      INSERT INTO expert_profiles (
        id, project_id, agent_key, display_name, role_profile, responsibility_scope, excluded_scope,
        enabled, min_confidence, max_findings, max_llm_calls, max_tool_calls, output_schema_version
      )
      SELECT 'profile_' || substr(md5(random()::text || clock_timestamp()::text), 1, 16), $1, agent_key, display_name, role_profile, responsibility_scope, excluded_scope,
        enabled, min_confidence, max_findings, max_llm_calls, max_tool_calls, output_schema_version
      FROM expert_profiles
      WHERE project_id = $2
      ON CONFLICT DO NOTHING
    `).run(targetProjectId, sourceProjectId);
    this.db.prepare(`
      INSERT INTO agent_configs (
        id, project_id, agent_id, display_name, enabled, applies_to_json, tools_json,
        skills_json, rule_sets_json, requires_deepagents, min_confidence, max_findings_per_mr
      )
      SELECT 'agent_' || substr(md5(random()::text || clock_timestamp()::text), 1, 16), $1, agent_id, display_name, enabled, applies_to_json, tools_json,
        skills_json, rule_sets_json, requires_deepagents, min_confidence, max_findings_per_mr
      FROM agent_configs
      WHERE project_id = $2
      ON CONFLICT DO NOTHING
    `).run(targetProjectId, sourceProjectId);
    this.db.prepare(`
      INSERT INTO expert_skill_bindings (id, project_id, agent_key, skill_key, priority, enabled)
      SELECT 'skill_binding_' || substr(md5(random()::text || clock_timestamp()::text), 1, 16), $1, agent_key, skill_key, priority, enabled
      FROM expert_skill_bindings
      WHERE project_id = $2
      ON CONFLICT DO NOTHING
    `).run(targetProjectId, sourceProjectId);
    this.db.prepare(`
      INSERT INTO expert_tool_bindings (id, project_id, agent_key, tool_name, permission_level, max_calls, enabled)
      SELECT 'tool_binding_' || substr(md5(random()::text || clock_timestamp()::text), 1, 16), $1, agent_key, tool_name, permission_level, max_calls, enabled
      FROM expert_tool_bindings
      WHERE project_id = $2
      ON CONFLICT DO NOTHING
    `).run(targetProjectId, sourceProjectId);
    const sourceDocs = this.db.prepare("SELECT id, name FROM rule_documents WHERE project_id = $1").all(sourceProjectId) as Array<{ id: string; name: string }>;
    for (const sourceDoc of sourceDocs) {
      const targetDoc = this.db.prepare("SELECT id FROM rule_documents WHERE project_id = $1 AND name = $2 ORDER BY created_at DESC LIMIT 1")
        .get(targetProjectId, sourceDoc.name) as { id: string } | undefined;
      if (!targetDoc) continue;
      this.db.prepare(`
        INSERT INTO expert_rule_bindings (id, project_id, agent_key, rule_document_id, priority)
        SELECT 'rule_binding_' || substr(md5(random()::text || clock_timestamp()::text), 1, 16), $1, agent_key, $2, priority
        FROM expert_rule_bindings
        WHERE project_id = $3 AND rule_document_id = $4
        ON CONFLICT DO NOTHING
      `).run(targetProjectId, targetDoc.id, sourceProjectId, sourceDoc.id);
    }
  }
}
