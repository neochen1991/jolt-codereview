import { createHash } from "node:crypto";
import type { Db } from "../db.js";
import type { AppConfig } from "../types.js";
import { canonicalSkillBundleHash, resolveCanonicalSkillVersion } from "../repositories/RuleDocumentRepository.js";

const SECRET_KEY = /(^|_)(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|secret|token)$/i;

function redactSecrets(value: unknown, key = ""): unknown {
  if (SECRET_KEY.test(key)) return "<redacted>";
  if (Array.isArray(value)) return value.map((item) => redactSecrets(item));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([childKey, child]) => [childKey, redactSecrets(child, childKey)]));
  }
  return value;
}

export function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function parseStoredObject(value: unknown, label: string) {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, any>;
  const raw = String(value || "").trim();
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, any> : {};
  } catch {
    throw new Error(`Skill latest checkpoint compilation failed: malformed ${label}`);
  }
}

export function assertSkillVersionCompilationReady(skill: Record<string, any>) {
  const validation = parseStoredObject(skill.validation_json, "validation report");
  const manifest = parseStoredObject(skill.checkpoint_manifest_json, "checkpoint manifest");
  if (validation.ok === false || manifest.ok === false) {
    const failures = Array.isArray(validation.failures) ? validation.failures : [];
    const detail = failures
      .slice(0, 3)
      .map((item: Record<string, any>) => String(item.message || item.code || "checkpoint compilation error"))
      .join("; ");
    throw new Error(`Skill latest checkpoint compilation failed${detail ? `: ${detail}` : ""}`);
  }
}

export class SkillDebugSnapshotService {
  constructor(private readonly db: Db) {}

  build(input: {
    projectId: string;
    mergeRequest: Record<string, any>;
    repository: Record<string, any>;
    skillKey: string;
    skillVersion?: string | null;
    agentKey: string;
    effectiveConfig: AppConfig;
  }) {
    const skill = resolveCanonicalSkillVersion(this.db, input.projectId, input.skillKey, input.skillVersion);
    if (!skill) throw new Error("Skill version not found");
    assertSkillVersionCompilationReady(skill);
    const agent = this.db.prepare("SELECT * FROM expert_profiles WHERE project_id = $1 AND agent_key = $2")
      .get(input.projectId, input.agentKey) as Record<string, any> | undefined;
    if (!agent) throw new Error("Agent not found");
    const rules = this.db.prepare(`
      SELECT erb.*, rd.name, rd.version, rd.status, rd.content
      FROM expert_rule_bindings erb
      JOIN rule_documents rd ON rd.id = erb.rule_document_id
      WHERE erb.project_id = $1 AND erb.agent_key = $2
      ORDER BY erb.priority, erb.id
    `).all(input.projectId, input.agentKey);
    const tools = this.db.prepare(`
      SELECT * FROM expert_tool_bindings
      WHERE project_id = $1 AND agent_key = $2 AND enabled = 1
      ORDER BY tool_name
    `).all(input.projectId, input.agentKey);
    const skillBindings = this.db.prepare(`
      SELECT * FROM expert_skill_bindings
      WHERE project_id = $1 AND agent_key = $2
      ORDER BY priority, skill_key
    `).all(input.projectId, input.agentKey);
    const snapshot = redactSecrets({
      version: "skill_debug_snapshot_v1",
      contract: "production_review_pipeline_v1",
      mr: { id: input.mergeRequest.id, head_sha: input.mergeRequest.latest_head_sha, repository_id: input.repository.id },
      skill: {
        id: skill.id, skill_key: skill.skill_key, version: skill.version, name: skill.name,
        description: skill.description, content: skill.content, status: skill.status,
        bundle_sha256: skill.bundle_sha256 || canonicalSkillBundleHash(skill),
        checkpoint_manifest: parseStoredObject(skill.checkpoint_manifest_json, "checkpoint manifest"),
        checkpoint_compiler_version: skill.checkpoint_compiler_version
      },
      assets: JSON.parse(String(skill.assets_json || "[]")),
      agent,
      bindings: { skills: skillBindings, rules, tools },
      config: {
        llm: input.effectiveConfig.llm || {},
        data_policy: input.effectiveConfig.data_policy || {},
        queue_policy: input.effectiveConfig.queue_policy || {}
      }
    }) as Record<string, unknown>;
    const snapshot_sha256 = createHash("sha256").update(stableStringify(snapshot)).digest("hex");
    return { snapshot, snapshot_sha256 };
  }
}
