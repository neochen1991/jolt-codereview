import type { Db } from "../db.js";

export class ProjectRepository {
  constructor(private readonly db: Db) {}

  findActiveUserByUsername(username: string) {
    return this.db.prepare("SELECT * FROM users WHERE username = ? AND status = 'active'").get(username);
  }

  createAuthSession(id: string, userId: string, tokenHash: string) {
    this.db.prepare(`
      INSERT INTO auth_sessions (id, user_id, token_hash, status, expires_at)
      VALUES (?, ?, ?, 'active', datetime('now', '+7 days'))
    `).run(id, userId, tokenHash);
  }

  revokeSession(tokenHash: string) {
    this.db.prepare("UPDATE auth_sessions SET status = 'revoked' WHERE token_hash = ?").run(tokenHash);
  }

  findSessionUserId(tokenHash: string) {
    return this.db.prepare(
      "SELECT user_id FROM auth_sessions WHERE token_hash = ? AND status = 'active' AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)"
    ).get(tokenHash);
  }

  findUserById(userId: string) {
    return this.db.prepare("SELECT * FROM users WHERE id = ?").get(userId);
  }

  listProjects() {
    return this.db.prepare("SELECT * FROM projects ORDER BY created_at").all();
  }

  findProjectById(projectId: string) {
    return this.db.prepare("SELECT * FROM projects WHERE id = ?").get(projectId);
  }

  createProject(input: {
    id: string;
    name: string;
    description: string;
    ownerUserId: string;
    memberId: string;
    cloneFromProjectId?: string;
  }) {
    const cloneFromProjectId = input.cloneFromProjectId || "project_default";
    this.db.exec("BEGIN");
    try {
      const source = this.findProjectById(cloneFromProjectId) as { data_policy_json?: string } | undefined;
      this.db.prepare(`
        INSERT INTO projects (id, name, description, data_policy_json)
        VALUES (?, ?, ?, ?)
      `).run(input.id, input.name, input.description, source?.data_policy_json || "{}");
      this.db.prepare(`
        INSERT INTO project_members (id, project_id, user_id, role)
        VALUES (?, ?, ?, 'project_admin')
      `).run(input.memberId, input.id, input.ownerUserId);
      this.cloneDefaults(cloneFromProjectId, input.id);
      this.db.exec("COMMIT");
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
    return this.findProjectById(input.id);
  }

  private cloneDefaults(sourceProjectId: string, targetProjectId: string) {
    const suffix = targetProjectId.replace(/[^a-zA-Z0-9]+/g, "_");
    this.db.prepare(`
      INSERT OR IGNORE INTO review_policy (id, project_id, policy_json)
      SELECT ?, ?, policy_json
      FROM review_policy
      WHERE project_id = ?
    `).run(`policy_${suffix}`, targetProjectId, sourceProjectId);
    this.db.prepare(`
      INSERT OR IGNORE INTO project_settings (id, project_id, settings_key, settings_json)
      SELECT 'setting_' || settings_key || '_' || ?, ?, settings_key, settings_json
      FROM project_settings
      WHERE project_id = ?
    `).run(suffix, targetProjectId, sourceProjectId);
    this.db.prepare(`
      INSERT OR IGNORE INTO rule_sets (id, project_id, name, version, scope_json, content, status)
      SELECT 'rules_' || lower(hex(randomblob(8))), ?, name, version, scope_json, content, status
      FROM rule_sets
      WHERE project_id = ?
    `).run(targetProjectId, sourceProjectId);
    this.db.prepare(`
      INSERT OR IGNORE INTO rule_documents (id, project_id, name, doc_type, content, version, status)
      SELECT 'rule_doc_' || lower(hex(randomblob(8))), ?, name, doc_type, content, version, status
      FROM rule_documents
      WHERE project_id = ?
    `).run(targetProjectId, sourceProjectId);
    this.db.prepare(`
      INSERT OR IGNORE INTO custom_skills (id, project_id, skill_key, name, description, content, version, status)
      SELECT 'skill_' || lower(hex(randomblob(8))), ?, skill_key, name, description, content, version, status
      FROM custom_skills
      WHERE project_id = ?
    `).run(targetProjectId, sourceProjectId);
    this.db.prepare(`
      INSERT OR IGNORE INTO custom_skill_assets (id, project_id, skill_key, asset_path, asset_type, content, executable)
      SELECT 'skill_asset_' || lower(hex(randomblob(8))), ?, skill_key, asset_path, asset_type, content, executable
      FROM custom_skill_assets
      WHERE project_id = ?
    `).run(targetProjectId, sourceProjectId);
    this.db.prepare(`
      INSERT OR IGNORE INTO expert_profiles (
        id, project_id, agent_key, display_name, role_profile, responsibility_scope, excluded_scope,
        enabled, min_confidence, max_findings, max_llm_calls, max_tool_calls, output_schema_version
      )
      SELECT 'profile_' || lower(hex(randomblob(8))), ?, agent_key, display_name, role_profile, responsibility_scope, excluded_scope,
        enabled, min_confidence, max_findings, max_llm_calls, max_tool_calls, output_schema_version
      FROM expert_profiles
      WHERE project_id = ?
    `).run(targetProjectId, sourceProjectId);
    this.db.prepare(`
      INSERT OR IGNORE INTO agent_configs (
        id, project_id, agent_id, display_name, enabled, applies_to_json, tools_json,
        skills_json, rule_sets_json, requires_deepagents, min_confidence, max_findings_per_mr
      )
      SELECT 'agent_' || lower(hex(randomblob(8))), ?, agent_id, display_name, enabled, applies_to_json, tools_json,
        skills_json, rule_sets_json, requires_deepagents, min_confidence, max_findings_per_mr
      FROM agent_configs
      WHERE project_id = ?
    `).run(targetProjectId, sourceProjectId);
    this.db.prepare(`
      INSERT OR IGNORE INTO expert_skill_bindings (id, project_id, agent_key, skill_key, priority, enabled)
      SELECT 'skill_binding_' || lower(hex(randomblob(8))), ?, agent_key, skill_key, priority, enabled
      FROM expert_skill_bindings
      WHERE project_id = ?
    `).run(targetProjectId, sourceProjectId);
    this.db.prepare(`
      INSERT OR IGNORE INTO expert_tool_bindings (id, project_id, agent_key, tool_name, permission_level, max_calls, enabled)
      SELECT 'tool_binding_' || lower(hex(randomblob(8))), ?, agent_key, tool_name, permission_level, max_calls, enabled
      FROM expert_tool_bindings
      WHERE project_id = ?
    `).run(targetProjectId, sourceProjectId);
    const sourceDocs = this.db.prepare("SELECT id, name FROM rule_documents WHERE project_id = ?").all(sourceProjectId) as Array<{ id: string; name: string }>;
    for (const sourceDoc of sourceDocs) {
      const targetDoc = this.db.prepare("SELECT id FROM rule_documents WHERE project_id = ? AND name = ? ORDER BY created_at DESC LIMIT 1")
        .get(targetProjectId, sourceDoc.name) as { id: string } | undefined;
      if (!targetDoc) continue;
      this.db.prepare(`
        INSERT OR IGNORE INTO expert_rule_bindings (id, project_id, agent_key, rule_document_id, priority)
        SELECT 'rule_binding_' || lower(hex(randomblob(8))), ?, agent_key, ?, priority
        FROM expert_rule_bindings
        WHERE project_id = ? AND rule_document_id = ?
      `).run(targetProjectId, targetDoc.id, sourceProjectId, sourceDoc.id);
    }
  }

  updateProject(projectId: string, input: Record<string, unknown>) {
    this.db.prepare(`
      UPDATE projects
      SET name = COALESCE(?, name),
          description = COALESCE(?, description),
          data_policy_json = COALESCE(?, data_policy_json)
      WHERE id = ?
    `).run(
      typeof input.name === "string" ? input.name : null,
      typeof input.description === "string" ? input.description : null,
      typeof input.data_policy === "object" && input.data_policy ? JSON.stringify(input.data_policy) : null,
      projectId
    );
    return this.findProjectById(projectId);
  }

  listProjectsForUser(userId: string) {
    return this.db.prepare(`
      SELECT p.*, pm.role
      FROM projects p
      JOIN project_members pm ON pm.project_id = p.id
      WHERE pm.user_id = ?
    `).all(userId);
  }

  findMemberRole(projectId: string, userId: string) {
    return this.db.prepare("SELECT role FROM project_members WHERE project_id = ? AND user_id = ?").get(projectId, userId);
  }

  listMembers(projectId: string) {
    return this.db.prepare(`
      SELECT pm.*, u.username, u.display_name, u.email, u.status
      FROM project_members pm
      JOIN users u ON u.id = pm.user_id
      WHERE pm.project_id = ?
      ORDER BY pm.role, u.username
    `).all(projectId);
  }

  upsertMember(input: {
    userId: string;
    username: string;
    displayName: string;
    email?: string | null;
    memberId: string;
    projectId: string;
    role: string;
  }) {
    this.db.prepare(`
      INSERT OR IGNORE INTO users (id, username, display_name, email, status)
      VALUES (?, ?, ?, ?, 'active')
    `).run(input.userId, input.username, input.displayName, input.email ?? null);
    this.db.prepare(`
      INSERT INTO project_members (id, project_id, user_id, role)
      VALUES (?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET role = excluded.role
    `).run(input.memberId, input.projectId, input.userId, input.role);
    return this.db.prepare("SELECT * FROM project_members WHERE id = ?").get(input.memberId);
  }

  updateMemberRole(projectId: string, memberId: string, role: string) {
    this.db.prepare("UPDATE project_members SET role = ? WHERE id = ? AND project_id = ?").run(role, memberId, projectId);
  }

  findMember(projectId: string, memberId: string) {
    return this.db.prepare("SELECT * FROM project_members WHERE id = ? AND project_id = ?").get(memberId, projectId);
  }

  deleteMember(projectId: string, memberId: string) {
    this.db.prepare("DELETE FROM project_members WHERE id = ? AND project_id = ?").run(memberId, projectId);
  }
}
