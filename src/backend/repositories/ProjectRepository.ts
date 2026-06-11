import type { Db } from "../db.js";

export class ProjectRepository {
  constructor(private readonly db: Db) {}

  findActiveUserByUsername(username: string) {
    return this.db.prepare("SELECT * FROM users WHERE username = ? AND status = 'active'").get(username);
  }

  createUser(input: {
    id: string;
    username: string;
    displayName: string;
    email?: string | null;
    passwordHash: string;
    passwordSalt: string;
    globalRole?: string;
  }) {
    this.db.prepare(`
      INSERT INTO users (id, username, display_name, email, password_hash, password_salt, global_role, status)
      VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
    `).run(
      input.id,
      input.username,
      input.displayName,
      input.email ?? null,
      input.passwordHash,
      input.passwordSalt,
      input.globalRole ?? "user"
    );
    return this.findUserById(input.id);
  }

  markLogin(userId: string) {
    this.db.prepare("UPDATE users SET last_login_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?").run(userId);
  }

  updateUserPassword(userId: string, passwordHash: string, passwordSalt: string) {
    this.db.prepare(`
      UPDATE users
      SET password_hash = ?, password_salt = ?, updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
    `).run(passwordHash, passwordSalt, userId);
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

  isRoot(userId: string) {
    const user = this.findUserById(userId) as { global_role?: string } | undefined;
    return user?.global_role === "root";
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
      ORDER BY p.created_at
    `).all(userId);
  }

  listDiscoverableProjects(userId: string) {
    return this.db.prepare(`
      SELECT
        p.*,
        pm.role,
        r.status AS join_request_status,
        r.requested_role AS requested_role
      FROM projects p
      LEFT JOIN project_members pm
        ON pm.project_id = p.id AND pm.user_id = ?
      LEFT JOIN project_join_requests r
        ON r.project_id = p.id AND r.user_id = ? AND r.status = 'pending'
      ORDER BY p.created_at
    `).all(userId, userId);
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
    const existingUser = this.findActiveUserByUsername(input.username) as { id: string } | undefined;
    const actualUserId = existingUser?.id ?? input.userId;
    const actualMemberId = existingUser
      ? `member_${input.projectId}_${actualUserId}`.replace(/[^a-zA-Z0-9_]+/g, "_").slice(0, 80)
      : input.memberId;
    this.db.prepare(`
      INSERT OR IGNORE INTO users (id, username, display_name, email, status)
      VALUES (?, ?, ?, ?, 'active')
    `).run(actualUserId, input.username, input.displayName, input.email ?? null);
    this.db.prepare("DELETE FROM project_members WHERE project_id = ? AND user_id = ? AND id <> ?")
      .run(input.projectId, actualUserId, actualMemberId);
    this.db.prepare(`
      INSERT INTO project_members (id, project_id, user_id, role)
      VALUES (?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET role = excluded.role
    `).run(actualMemberId, input.projectId, actualUserId, input.role);
    return this.db.prepare("SELECT * FROM project_members WHERE id = ?").get(actualMemberId);
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

  listUserSettings(userId: string) {
    return this.db.prepare(`
      SELECT settings_key, settings_json, updated_at
      FROM user_settings
      WHERE user_id = ?
      ORDER BY settings_key
    `).all(userId);
  }

  upsertUserSetting(input: {
    id: string;
    userId: string;
    key: string;
    value: Record<string, unknown>;
  }) {
    this.db.prepare(`
      INSERT INTO user_settings (id, user_id, settings_key, settings_json, updated_at)
      VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
      ON CONFLICT(user_id, settings_key) DO UPDATE SET
        settings_json = excluded.settings_json,
        updated_at = CURRENT_TIMESTAMP
    `).run(input.id, input.userId, input.key, JSON.stringify(input.value));
    return this.db.prepare(`
      SELECT settings_key AS key, settings_json, updated_at
      FROM user_settings
      WHERE user_id = ? AND settings_key = ?
    `).get(input.userId, input.key);
  }

  createJoinRequest(input: {
    id: string;
    projectId: string;
    userId: string;
    requestedRole: string;
    reason: string;
  }) {
    this.db.prepare(`
      INSERT INTO project_join_requests (id, project_id, user_id, requested_role, reason, status)
      VALUES (?, ?, ?, ?, ?, 'pending')
      ON CONFLICT(project_id, user_id, status) DO UPDATE SET
        requested_role = excluded.requested_role,
        reason = excluded.reason,
        updated_at = CURRENT_TIMESTAMP
    `).run(input.id, input.projectId, input.userId, input.requestedRole, input.reason);
    return this.db.prepare("SELECT * FROM project_join_requests WHERE project_id = ? AND user_id = ? AND status = 'pending'")
      .get(input.projectId, input.userId);
  }

  listJoinRequests(projectId: string) {
    return this.db.prepare(`
      SELECT r.*, u.username, u.display_name, u.email
      FROM project_join_requests r
      JOIN users u ON u.id = r.user_id
      WHERE r.project_id = ?
      ORDER BY r.created_at DESC
    `).all(projectId);
  }

  reviewJoinRequest(input: {
    projectId: string;
    requestId: string;
    reviewerId: string;
    status: "approved" | "rejected";
  }) {
    const request = this.db.prepare("SELECT * FROM project_join_requests WHERE id = ? AND project_id = ?")
      .get(input.requestId, input.projectId) as { user_id: string; requested_role: string } | undefined;
    if (!request) return null;
    this.db.prepare(`
      UPDATE project_join_requests
      SET status = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
      WHERE id = ? AND project_id = ?
    `).run(input.status, input.reviewerId, input.requestId, input.projectId);
    if (input.status === "approved") {
      const memberId = `member_${input.projectId}_${request.user_id}`.replace(/[^a-zA-Z0-9_]+/g, "_").slice(0, 80);
      this.db.prepare("DELETE FROM project_members WHERE project_id = ? AND user_id = ? AND id <> ?")
        .run(input.projectId, request.user_id, memberId);
      this.db.prepare(`
        INSERT INTO project_members (id, project_id, user_id, role)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET role = excluded.role
      `).run(memberId, input.projectId, request.user_id, request.requested_role || "developer");
    }
    return this.db.prepare("SELECT * FROM project_join_requests WHERE id = ?").get(input.requestId);
  }

  createInvitation(input: {
    id: string;
    projectId: string;
    inviteCodeHash: string;
    role: string;
    createdBy: string;
    expiresAt?: string | null;
    maxUses?: number;
  }) {
    this.db.prepare(`
      INSERT INTO project_invitations (id, project_id, invite_code_hash, role, created_by, expires_at, max_uses, status)
      VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
    `).run(
      input.id,
      input.projectId,
      input.inviteCodeHash,
      input.role,
      input.createdBy,
      input.expiresAt ?? null,
      input.maxUses ?? 1
    );
    return this.db.prepare("SELECT * FROM project_invitations WHERE id = ?").get(input.id);
  }

  listInvitations(projectId: string) {
    return this.db.prepare(`
      SELECT i.*, u.username AS created_by_username
      FROM project_invitations i
      LEFT JOIN users u ON u.id = i.created_by
      WHERE i.project_id = ?
      ORDER BY i.created_at DESC
    `).all(projectId);
  }

  redeemInvitation(input: {
    inviteCodeHash: string;
    userId: string;
  }) {
    const invitation = this.db.prepare(`
      SELECT *
      FROM project_invitations
      WHERE invite_code_hash = ?
        AND status = 'active'
        AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
        AND used_count < max_uses
    `).get(input.inviteCodeHash) as { id: string; project_id: string; role: string; used_count: number } | undefined;
    if (!invitation) return null;
    const memberId = `member_${invitation.project_id}_${input.userId}`.replace(/[^a-zA-Z0-9_]+/g, "_").slice(0, 80);
    this.db.prepare("DELETE FROM project_members WHERE project_id = ? AND user_id = ? AND id <> ?")
      .run(invitation.project_id, input.userId, memberId);
    this.db.prepare(`
      INSERT INTO project_members (id, project_id, user_id, role)
      VALUES (?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET role = excluded.role
    `).run(memberId, invitation.project_id, input.userId, invitation.role || "developer");
    this.db.prepare(`
      UPDATE project_invitations
      SET used_count = used_count + 1,
          status = CASE WHEN used_count + 1 >= max_uses THEN 'used' ELSE status END
      WHERE id = ?
    `).run(invitation.id);
    return this.findProjectById(invitation.project_id);
  }
}
