import type { Db } from "../db.js";
import type { AppConfig } from "../types.js";

const SETTINGS_KEYS = [
  "llm_policy",
  "vcs_policy",
  "review_policy",
  "budget_policy",
  "agent_policy",
  "tool_policy",
  "queue_policy",
  "publish_policy",
  "data_policy",
  "token_usage"
] as const;

export type ProjectSettingsKey = typeof SETTINGS_KEYS[number];

export class ProjectConfigService {
  constructor(private readonly db: Db) {}

  allowedKeys() {
    return [...SETTINGS_KEYS];
  }

  isAllowedKey(key: string): key is ProjectSettingsKey {
    return SETTINGS_KEYS.includes(key as ProjectSettingsKey);
  }

  listSettings(projectId: string) {
    const rows = this.db.prepare(`
      SELECT settings_key, settings_json, updated_at
      FROM project_settings
      WHERE project_id = ?
      ORDER BY settings_key
    `).all(projectId) as Array<{ settings_key: string; settings_json: string; updated_at: string }>;
    const settings = Object.fromEntries(
      SETTINGS_KEYS.map((key) => [key, {} as Record<string, unknown>])
    );
    for (const row of rows) {
      settings[row.settings_key] = JSON.parse(row.settings_json || "{}");
    }
    return {
      project_id: projectId,
      allowed_keys: this.allowedKeys(),
      settings,
      items: rows.map((row) => ({
        key: row.settings_key,
        value: JSON.parse(row.settings_json || "{}"),
        updated_at: row.updated_at
      }))
    };
  }

  upsertSetting(projectId: string, key: ProjectSettingsKey, value: Record<string, unknown>) {
    const settingId = `setting_${projectId}_${key}`;
    this.db.prepare(`
      INSERT INTO project_settings (id, project_id, settings_key, settings_json, updated_at)
      VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
      ON CONFLICT(project_id, settings_key) DO UPDATE SET
        settings_json = excluded.settings_json,
        updated_at = CURRENT_TIMESTAMP
    `).run(settingId, projectId, key, JSON.stringify(value));
    return this.db.prepare(`
      SELECT settings_key AS key, settings_json, updated_at
      FROM project_settings
      WHERE project_id = ? AND settings_key = ?
    `).get(projectId, key) as { key: string; settings_json: string; updated_at: string } | undefined;
  }

  effectiveConfig(projectId: string, deploymentDefaults: AppConfig) {
    const settings = this.listSettings(projectId).settings as Record<string, Record<string, unknown>>;
    const effective = JSON.parse(JSON.stringify(deploymentDefaults ?? {})) as AppConfig;
    if (settings.llm_policy && Object.keys(settings.llm_policy).length > 0) {
      effective.llm = {
        ...(effective.llm ?? {}),
        ...settings.llm_policy
      };
    }
    if (settings.vcs_policy && Object.keys(settings.vcs_policy).length > 0) {
      const vcsPolicy = settings.vcs_policy;
      effective.github = {
        ...(effective.github ?? {}),
        ...(vcsPolicy.github_token ? { default_token: vcsPolicy.github_token as string } : {}),
        ...(vcsPolicy.github_token_env ? { default_token_env: vcsPolicy.github_token_env as string } : {}),
        ...(vcsPolicy.github_endpoint ? { default_endpoint: vcsPolicy.github_endpoint as string } : {})
      };
      effective.codehub = {
        ...(effective.codehub ?? {}),
        ...(vcsPolicy.codehub_token ? { default_token: vcsPolicy.codehub_token as string } : {}),
        ...(vcsPolicy.codehub_token_env ? { default_token_env: vcsPolicy.codehub_token_env as string } : {}),
        ...(vcsPolicy.codehub_endpoint ? { default_endpoint: vcsPolicy.codehub_endpoint as string } : {})
      };
    }
    for (const key of SETTINGS_KEYS) {
      if (key === "llm_policy" || key === "vcs_policy") continue;
      const value = settings[key];
      if (value && Object.keys(value).length > 0) {
        const configKey = key === "token_usage" ? "token_usage" : key;
        const current = (effective as Record<string, unknown>)[configKey];
        (effective as Record<string, unknown>)[configKey] =
          current && typeof current === "object" && !Array.isArray(current)
            ? { ...(current as Record<string, unknown>), ...value }
            : value;
      }
    }
    return {
      project_id: projectId,
      source: {
        deployment_defaults: true,
        project_settings: Object.fromEntries(
          Object.entries(settings).filter(([, value]) => Object.keys(value).length > 0)
        )
      },
      effective_config: effective
    };
  }
}
