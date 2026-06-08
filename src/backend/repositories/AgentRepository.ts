import type { Db } from "../db.js";

export class AgentRepository {
  constructor(private readonly db: Db) {}

  listByProject(projectId: string) {
    return this.db.prepare("SELECT * FROM agent_configs WHERE project_id = ? ORDER BY agent_id").all(projectId);
  }

  listWithProfiles(projectId: string) {
    return this.db.prepare(`
      SELECT
        ac.*,
        ep.role_profile,
        ep.responsibility_scope,
        ep.excluded_scope,
        ep.max_llm_calls,
        ep.max_tool_calls,
        ep.output_schema_version
      FROM agent_configs ac
      LEFT JOIN expert_profiles ep
        ON ep.project_id = ac.project_id
       AND ep.agent_key = ac.agent_id
      WHERE ac.project_id = ?
      ORDER BY ac.agent_id
    `).all(projectId);
  }

  listExpertProfiles(projectId: string) {
    return this.db.prepare("SELECT * FROM expert_profiles WHERE project_id = ? ORDER BY agent_key").all(projectId);
  }

  findExpertProfile(projectId: string, agentKey: string) {
    return this.db.prepare("SELECT * FROM expert_profiles WHERE project_id = ? AND agent_key = ?").get(projectId, agentKey);
  }

  findByProjectAndAgent(projectId: string, agentId: string) {
    return this.db.prepare("SELECT * FROM agent_configs WHERE project_id = ? AND agent_id = ?").get(projectId, agentId);
  }

  createCustomAgent(input: {
    id: string;
    profileId: string;
    projectId: string;
    agentKey: string;
    displayName: string;
    roleProfile: string;
    responsibilityScope: string;
    excludedScope: string;
    appliesTo: Record<string, unknown>;
    tools: string[];
    skills: string[];
    ruleSets: string[];
    requiresDeepagents: boolean;
    minConfidence: number;
    maxFindings: number;
    maxLlmCalls: number;
    maxToolCalls: number;
  }) {
    const tx = this.db.prepare(`
      INSERT INTO expert_profiles (
        id, project_id, agent_key, display_name, role_profile, responsibility_scope, excluded_scope,
        enabled, min_confidence, max_findings, max_llm_calls, max_tool_calls, output_schema_version
      )
      VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, 'finding_v1')
      ON CONFLICT(project_id, agent_key) DO UPDATE SET
        display_name = excluded.display_name,
        role_profile = excluded.role_profile,
        responsibility_scope = excluded.responsibility_scope,
        excluded_scope = excluded.excluded_scope,
        enabled = 1,
        min_confidence = excluded.min_confidence,
        max_findings = excluded.max_findings,
        max_llm_calls = excluded.max_llm_calls,
        max_tool_calls = excluded.max_tool_calls
    `);
    tx.run(
      input.profileId,
      input.projectId,
      input.agentKey,
      input.displayName,
      input.roleProfile,
      input.responsibilityScope,
      input.excludedScope,
      input.minConfidence,
      input.maxFindings,
      input.maxLlmCalls,
      input.maxToolCalls
    );
    this.db.prepare(`
      INSERT INTO agent_configs (
        id, project_id, agent_id, display_name, enabled, applies_to_json, tools_json,
        skills_json, rule_sets_json, requires_deepagents, min_confidence, max_findings_per_mr
      )
      VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(project_id, agent_id) DO UPDATE SET
        display_name = excluded.display_name,
        enabled = 1,
        applies_to_json = excluded.applies_to_json,
        tools_json = excluded.tools_json,
        skills_json = excluded.skills_json,
        rule_sets_json = excluded.rule_sets_json,
        requires_deepagents = excluded.requires_deepagents,
        min_confidence = excluded.min_confidence,
        max_findings_per_mr = excluded.max_findings_per_mr,
        updated_at = CURRENT_TIMESTAMP
    `).run(
      input.id,
      input.projectId,
      input.agentKey,
      input.displayName,
      JSON.stringify(input.appliesTo),
      JSON.stringify(input.tools),
      JSON.stringify(input.skills),
      JSON.stringify(input.ruleSets),
      input.requiresDeepagents ? 1 : 0,
      input.minConfidence,
      input.maxFindings
    );
    return this.findExpertProfile(input.projectId, input.agentKey);
  }

  update(projectId: string, agentId: string, input: Record<string, unknown>) {
    this.db.prepare(`
      UPDATE agent_configs
      SET enabled = COALESCE(?, enabled),
          applies_to_json = COALESCE(?, applies_to_json),
          tools_json = COALESCE(?, tools_json),
          skills_json = COALESCE(?, skills_json),
          rule_sets_json = COALESCE(?, rule_sets_json),
          min_confidence = COALESCE(?, min_confidence),
          max_findings_per_mr = COALESCE(?, max_findings_per_mr),
          updated_at = CURRENT_TIMESTAMP
      WHERE project_id = ? AND agent_id = ?
    `).run(
      typeof input.enabled === "boolean" ? (input.enabled ? 1 : 0) : null,
      input.applies_to ? JSON.stringify(input.applies_to) : null,
      input.tools ? JSON.stringify(input.tools) : null,
      input.skills ? JSON.stringify(input.skills) : null,
      input.rule_sets ? JSON.stringify(input.rule_sets) : null,
      typeof input.min_confidence === "number" ? input.min_confidence : null,
      typeof input.max_findings_per_mr === "number" ? input.max_findings_per_mr : null,
      projectId,
      agentId
    );
    return this.findByProjectAndAgent(projectId, agentId);
  }

  updateExpertProfile(projectId: string, agentKey: string, input: Record<string, unknown>) {
    this.db.prepare(`
      UPDATE expert_profiles
      SET display_name = COALESCE(?, display_name),
          role_profile = COALESCE(?, role_profile),
          responsibility_scope = COALESCE(?, responsibility_scope),
          excluded_scope = COALESCE(?, excluded_scope),
          enabled = COALESCE(?, enabled),
          min_confidence = COALESCE(?, min_confidence),
          max_findings = COALESCE(?, max_findings),
          max_llm_calls = COALESCE(?, max_llm_calls),
          max_tool_calls = COALESCE(?, max_tool_calls)
      WHERE project_id = ? AND agent_key = ?
    `).run(
      typeof input.display_name === "string" ? input.display_name : null,
      typeof input.role_profile === "string" ? input.role_profile : null,
      typeof input.responsibility_scope === "string" ? input.responsibility_scope : null,
      typeof input.excluded_scope === "string" ? input.excluded_scope : null,
      typeof input.enabled === "boolean" ? (input.enabled ? 1 : 0) : null,
      typeof input.min_confidence === "number" ? input.min_confidence : null,
      typeof input.max_findings === "number" ? input.max_findings : null,
      typeof input.max_llm_calls === "number" ? input.max_llm_calls : null,
      typeof input.max_tool_calls === "number" ? input.max_tool_calls : null,
      projectId,
      agentKey
    );
    return this.findExpertProfile(projectId, agentKey);
  }
}
