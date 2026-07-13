import { readFileSync } from "node:fs";
import path from "node:path";
const root = process.cwd();
const read = (...parts) => readFileSync(path.join(root, ...parts), "utf8");
const service = read("mr-backend", "src", "backend", "services", "SkillDebugDiagnosticService.ts");
const frontend = read("frontend", "src", "frontend", "components", "ConfigViews.tsx");
const checks = [
  [service, "targetAgentEvents", "trace events filtered to target agent"],
  [service, "targetSkillCheckpoints", "checkpoint events filtered to target Skill"],
  [service, "targetLlmCalls", "LLM calls filtered to target agent"],
  [service, "targetToolCalls", "tool calls filtered to target agent"],
  [service, "targetFindings", "findings filtered to target agent"],
  [service, "semanticFindingKey", "stable semantic finding comparison"],
  [service, "changed", "changed finding classification"],
  [service, 'attribution_scope: "target_agent_and_skill_checkpoints"', "diagnostic scope disclosure"],
  [frontend, "变化", "changed findings UI"]
];
const failures = checks.filter(([source, snippet]) => !source.includes(snippet)).map(([, , label]) => label);
if (failures.length) throw new Error(`skill debug attribution verification failed:\n${failures.join("\n")}`);
console.log(JSON.stringify({ ok: true, verified: "skill_debug_attribution" }, null, 2));
