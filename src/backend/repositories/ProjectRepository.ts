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
