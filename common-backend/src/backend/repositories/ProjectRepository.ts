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

  updateUserProfile(userId: string, input: { displayName: string; email?: string | null }) {
    this.db.prepare(`
      UPDATE users
      SET display_name = ?, email = ?, updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
    `).run(input.displayName, input.email ?? null, userId);
    return this.findUserById(userId);
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

  listProjectsForUser(userId: string) {
    return this.db.prepare(`
      SELECT p.*, pm.role
      FROM projects p
      JOIN project_members pm ON pm.project_id = p.id
      WHERE pm.user_id = ?
      ORDER BY p.created_at
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

  updateMemberRole(projectId: string, memberId: string, role: string) {
    this.db.prepare("UPDATE project_members SET role = ? WHERE id = ? AND project_id = ?").run(role, memberId, projectId);
  }

  findMember(projectId: string, memberId: string) {
    return this.db.prepare("SELECT * FROM project_members WHERE id = ? AND project_id = ?").get(memberId, projectId);
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
}
