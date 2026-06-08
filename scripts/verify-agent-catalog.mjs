import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { loadConfig, root } from "./config-utils.mjs";

const expectedAgents = [
  "performance_agent",
  "security_agent",
  "coding_agent",
  "ddd_agent",
  "frontend_agent",
  "test_agent",
  "redis_agent",
  "dependency_agent",
  "database_agent",
  "backend_agent"
];

function dbPath() {
  const config = loadConfig();
  return path.resolve(root, config.server?.database_path || "data/jolt-codereview.sqlite");
}

function asJson(value, fallback) {
  try {
    return JSON.parse(value || "");
  } catch {
    return fallback;
  }
}

const db = new DatabaseSync(dbPath());
const rows = db.prepare(`
  SELECT agent_id, display_name, enabled, applies_to_json, skills_json, tools_json
  FROM agent_configs
  WHERE project_id = 'project_default'
  ORDER BY agent_id
`).all();
db.close();

const byId = new Map(rows.map((row) => [row.agent_id, row]));
const missing = expectedAgents.filter((agentId) => !byId.has(agentId));
if (missing.length) throw new Error(`missing prebuilt expert agents: ${missing.join(", ")}`);

const enabledExpected = expectedAgents.filter((agentId) => byId.get(agentId)?.enabled === 1);
if (enabledExpected.length !== expectedAgents.length) {
  throw new Error(`not all prebuilt experts are enabled: ${enabledExpected.join(", ")}`);
}

const scopes = new Map();
for (const agentId of expectedAgents) {
  const row = byId.get(agentId);
  const appliesTo = asJson(row.applies_to_json, {});
  const skills = asJson(row.skills_json, []);
  const tools = asJson(row.tools_json, []);
  if (!appliesTo.persona || !appliesTo.review_scope || !appliesTo.exclusive_scope) {
    throw new Error(`${agentId} must define persona, review_scope and exclusive_scope`);
  }
  if (scopes.has(appliesTo.exclusive_scope)) {
    throw new Error(`${agentId} overlaps exclusive_scope with ${scopes.get(appliesTo.exclusive_scope)}`);
  }
  scopes.set(appliesTo.exclusive_scope, agentId);
  if (skills.length !== 1) throw new Error(`${agentId} must bind exactly one dedicated markdown skill`);
  if (tools.includes("static.heuristic_prescan")) {
    throw new Error(`${agentId} must not bind legacy static.heuristic_prescan by default`);
  }
  const skillPath = path.join(root, "agent-skills", skills[0], "SKILL.md");
  if (!existsSync(skillPath)) throw new Error(`${agentId} skill file does not exist: ${skillPath}`);
  const text = readFileSync(skillPath, "utf8");
  for (const marker of ["## 角色画像", "## 唯一检视范围", "## 专属代码规范", "## 输出要求"]) {
    if (!text.includes(marker)) throw new Error(`${agentId} skill ${skills[0]} misses section ${marker}`);
  }
  if (!text.includes("bound_standard: JAVA_WEB_STANDARD.md")) {
    throw new Error(`${agentId} skill ${skills[0]} must bind JAVA_WEB_STANDARD.md`);
  }
  const standardPath = path.join(root, "agent-skills", skills[0], "JAVA_WEB_STANDARD.md");
  if (!existsSync(standardPath)) throw new Error(`${agentId} standard file does not exist: ${standardPath}`);
  const standardText = readFileSync(standardPath, "utf8");
  for (const marker of ["### 规范说明", "### 检查点", "### 如何检查", "### 反例", "### 正例"]) {
    if (!standardText.includes(marker)) throw new Error(`${agentId} standard misses section ${marker}`);
  }
  const ruleCount = (standardText.match(/^##\s+[A-Z][A-Z0-9_-]+-\d+/gm) || []).length;
  if (ruleCount < 5) throw new Error(`${agentId} standard ${skills[0]}/JAVA_WEB_STANDARD.md must contain at least 5 structured rules`);
}

console.log(JSON.stringify({
  ok: true,
  agents: expectedAgents.map((agentId) => {
    const row = byId.get(agentId);
    const appliesTo = asJson(row.applies_to_json, {});
    const skills = asJson(row.skills_json, []);
    return {
      agent_id: agentId,
      display_name: row.display_name,
      exclusive_scope: appliesTo.exclusive_scope,
      skill: skills[0]
    };
  })
}, null, 2));
