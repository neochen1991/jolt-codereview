import type { Db } from "../db.js";

export class AuditRepository {
  constructor(private readonly db: Db) {}

  record(input: {
    id: string;
    userId?: string | null;
    projectId?: string | null;
    action: string;
    resourceType: string;
    resourceId?: string | null;
    summary?: string;
    metadata?: Record<string, unknown>;
  }) {
    this.db.prepare(`
      INSERT INTO audit_logs (id, user_id, project_id, action, resource_type, resource_id, summary, metadata_json)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      input.id,
      input.userId ?? null,
      input.projectId ?? null,
      input.action,
      input.resourceType,
      input.resourceId ?? null,
      input.summary ?? "",
      JSON.stringify(input.metadata ?? {})
    );
  }

  listForProject(projectId: string, limit: number) {
    return this.db.prepare(`
      SELECT al.*, u.username, u.display_name
      FROM audit_logs al
      LEFT JOIN users u ON u.id = al.user_id
      WHERE al.project_id = ? OR al.project_id IS NULL
      ORDER BY al.created_at DESC
      LIMIT ?
    `).all(projectId, limit);
  }
}
