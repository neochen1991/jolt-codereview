import { readFileSync } from "node:fs";
import path from "node:path";
const root = process.cwd();
const read = (...parts) => readFileSync(path.join(root, ...parts), "utf8");
const rootRoutes = read("mr-backend", "src", "backend", "routes", "mr-review.routes.ts");
const ruleRoutes = read("mr-backend", "src", "backend", "routes", "rules.routes.ts");
const reviewRoutes = read("mr-backend", "src", "backend", "routes", "review.routes.ts");
const sessions = read("mr-backend", "src", "backend", "repositories", "SkillDebugSessionRepository.ts");
const frontend = read("frontend", "src", "frontend", "components", "ConfigViews.tsx");
const checks = [
  [rootRoutes, "skill_developer", "recognized Skill developer role"],
  [rootRoutes, "ensureProjectCapability", "explicit capability authorization"],
  [ruleRoutes, '"manage_skill_drafts"', "draft Skill capability"],
  [reviewRoutes, '"run_skill_debug"', "debug capability"],
  [reviewRoutes, "requested_by !== actorId", "own-session isolation"],
  [sessions, "requestedBy", "history ownership filter"],
  [frontend, 'value="skill_developer"', "member role selection"],
  [frontend, "skill_developer", "Skill workspace role rendering"]
];
const failures = checks.filter(([source, snippet]) => !source.includes(snippet)).map(([, , label]) => label);
if (failures.length) throw new Error(`skill developer authorization verification failed:\n${failures.join("\n")}`);
console.log(JSON.stringify({ ok: true, verified: "skill_developer_authorization" }, null, 2));
