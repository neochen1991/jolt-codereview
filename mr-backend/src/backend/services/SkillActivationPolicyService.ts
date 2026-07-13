import type { Db } from "../db.js";

function parseJson(value: unknown): Record<string, any> {
  if (value && typeof value === "object") return value as Record<string, any>;
  try {
    const parsed = JSON.parse(String(value || "{}"));
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

export class SkillActivationPolicyService {
  constructor(private readonly db: Db) {}

  check(projectId: string, skillKey: string, version: string, bundleSha256: string) {
    const rows = this.db.prepare(`
      SELECT id, mode, status, validity_json, snapshot_json, bundle_sha256
      FROM skill_debug_sessions
      WHERE project_id = $1 AND skill_key = $2 AND skill_version = $3
        AND mode IN ('targeted', 'production_route')
      ORDER BY created_at DESC
    `).all(projectId, skillKey, version) as Array<Record<string, any>>;
    const validModes = new Set<string>();
    const evidence: Array<Record<string, unknown>> = [];
    for (const row of rows) {
      const validity = parseJson(row.validity_json);
      const snapshot = parseJson(row.snapshot_json);
      const evidenceHash = String(row.bundle_sha256 || snapshot?.skill?.bundle_sha256 || "");
      const conclusive = row.status === "completed" && validity.conclusive === true && evidenceHash === bundleSha256;
      evidence.push({ id: row.id, mode: row.mode, status: row.status, bundle_sha256: evidenceHash, conclusive });
      if (conclusive) validModes.add(String(row.mode));
    }
    const missing = ["targeted", "production_route"].filter((mode) => !validModes.has(mode));
    return { allowed: missing.length === 0, missing, evidence };
  }
}
