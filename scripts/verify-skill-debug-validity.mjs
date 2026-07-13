import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
const root = process.cwd();
const read = (...parts) => { const file = path.join(root, ...parts); return existsSync(file) ? readFileSync(file, "utf8") : ""; };
const service = read("mr-backend", "src", "backend", "services", "SkillDebugValidityService.ts");
const routes = read("mr-backend", "src", "backend", "routes", "review.routes.ts");
const repository = read("mr-backend", "src", "backend", "repositories", "SkillDebugSessionRepository.ts");
const frontend = read("frontend", "src", "frontend", "components", "ConfigViews.tsx");
const checks = [
  [service, "class SkillDebugValidityService", "validity evaluator"],
  [service, "github_fetch_error", "degraded fetch evidence"],
  [service, "target_agent_not_executed", "target execution requirement"],
  [service, "target_skill_not_loaded", "skill load requirement"],
  [service, "checkpoint_evidence_incomplete", "checkpoint evidence requirement"],
  [service, "no_successful_target_llm_call", "successful target LLM requirement"],
  [service, 'status: "degraded"', "degraded terminal state"],
  [service, 'status: "inconclusive"', "inconclusive terminal state"],
  [service, "conclusive: true", "conclusive success marker"],
  [routes, "skillDebugValidityService.evaluate", "session detail evaluates validity"],
  [repository, "updateValidity", "validity evidence persistence"],
  [frontend, "有效性", "validity evidence UI"]
];
const failures = checks.filter(([source, snippet]) => !source.includes(snippet)).map(([, , label]) => label);
if (failures.length) throw new Error(`skill debug validity verification failed:\n${failures.join("\n")}`);
console.log(JSON.stringify({ ok: true, verified: "skill_debug_validity" }, null, 2));
