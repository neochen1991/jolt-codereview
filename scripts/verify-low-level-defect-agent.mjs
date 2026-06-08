import path from "node:path";
import { openDatabase } from "../build/backend/db/connection.js";

const db = openDatabase({
  server: {
    database_path: path.join("/private/tmp", `jolt-low-level-agent-${process.pid}.sqlite`)
  }
});

function get(sql, params = []) {
  return db.prepare(sql).get(...params);
}

const agent = get(`
  SELECT ep.agent_key, ep.display_name, ep.role_profile, ep.responsibility_scope, ac.applies_to_json, ac.skills_json
  FROM expert_profiles ep
  JOIN agent_configs ac
    ON ac.project_id = ep.project_id
   AND ac.agent_id = ep.agent_key
  WHERE ep.project_id = 'project_default'
    AND ep.agent_key = 'low_level_defect_agent'
`);
if (!agent) throw new Error("low_level_defect_agent was not seeded");

const skill = get(`
  SELECT skill_key, name, content
  FROM custom_skills
  WHERE project_id = 'project_default'
    AND skill_key = 'java-low-level-defect-review'
    AND status = 'active'
`);
if (!skill) throw new Error("java-low-level-defect-review custom skill was not seeded");

const reference = get(`
  SELECT asset_path, asset_type, content
  FROM custom_skill_assets
  WHERE project_id = 'project_default'
    AND skill_key = 'java-low-level-defect-review'
    AND asset_path = 'references/java-low-level-defects.md'
`);
if (!reference) throw new Error("java low-level defect reference was not seeded");

const binding = get(`
  SELECT agent_key, skill_key, enabled
  FROM expert_skill_bindings
  WHERE project_id = 'project_default'
    AND agent_key = 'low_level_defect_agent'
    AND skill_key = 'java-low-level-defect-review'
    AND enabled = 1
`);
if (!binding) throw new Error("low_level_defect_agent skill binding was not seeded");

const appliesTo = JSON.parse(agent.applies_to_json || "{}");
const skills = JSON.parse(agent.skills_json || "[]");
for (const expected of ["custom_prompt", "java", "low_level_defect"]) {
  const text = JSON.stringify(appliesTo, null, 2).toLowerCase();
  if (!text.includes(expected)) throw new Error(`agent applies_to_json misses ${expected}`);
}
for (const expected of ["LLDEF-NULL-001", "LLDEF-MONEY-003", "LLDEF-RES-006", "LLDEF-CONC-007"]) {
  if (!reference.content.includes(expected)) throw new Error(`reference misses ${expected}`);
}
if (!skills.includes("java-low-level-defect-review")) {
  throw new Error(`agent skills_json does not include java-low-level-defect-review: ${agent.skills_json}`);
}

db.close();

console.log(JSON.stringify({
  ok: true,
  agent_key: agent.agent_key,
  display_name: agent.display_name,
  skill_key: skill.skill_key,
  reference: reference.asset_path,
  reference_rules_checked: ["LLDEF-NULL-001", "LLDEF-MONEY-003", "LLDEF-RES-006", "LLDEF-CONC-007"]
}, null, 2));
