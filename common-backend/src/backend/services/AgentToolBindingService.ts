import type { Db } from "../db.js";

export class AgentToolBindingService {
  constructor(private readonly db: Db) {}

  listBindings(projectId: string) {
    return this.db.prepare(`
      SELECT *
      FROM expert_tool_bindings
      WHERE project_id = ?
      ORDER BY agent_key, tool_name
    `).all(projectId);
  }

  upsertBinding(input: {
    id: string;
    projectId: string;
    agentKey: string;
    toolName: string;
    permissionLevel: string;
    maxCalls: number;
    enabled: boolean;
  }) {
    this.db.prepare(`
      INSERT INTO expert_tool_bindings (id, project_id, agent_key, tool_name, permission_level, max_calls, enabled)
      VALUES (?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(project_id, agent_key, tool_name) DO UPDATE SET
        permission_level = excluded.permission_level,
        max_calls = excluded.max_calls,
        enabled = excluded.enabled
    `).run(
      input.id,
      input.projectId,
      input.agentKey,
      input.toolName,
      input.permissionLevel,
      input.maxCalls,
      input.enabled ? 1 : 0
    );
    return this.listBindings(input.projectId);
  }
}
