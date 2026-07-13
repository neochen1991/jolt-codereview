import { readFileSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (...parts) => readFileSync(path.join(root, ...parts), "utf8");
const routes = read("mr-backend", "src", "backend", "routes", "review.routes.ts");
const migrations = read("mr-backend", "src", "backend", "db", "migrations.ts");
const repository = read("mr-backend", "src", "backend", "repositories", "ReviewJobRepository.ts");
const worker = read("mr-backend", "worker", "review_runtime.py");
const router = read("mr-backend", "worker", "orchestration", "nodes", "route_agents.py");
const frontend = read("frontend", "src", "frontend", "components", "ConfigViews.tsx");

const checks = [
  [migrations, "debug_context_json", "review_jobs debug context migration"],
  [repository, "debug_context_json", "queue persistence"],
  [routes, "/api/mr-review/merge-requests/:mrId/skill-debug-runs", "debug creation route"],
  [routes, "/api/mr-review/projects/:projectId/skill-debug-runs", "debug history route"],
  [routes, "/api/mr-review/skill-debug-runs/:jobId", "debug detail route"],
  [routes, "production_route", "production routing mode"],
  [routes, "targeted", "targeted routing mode"],
  [routes, "skill_debug.publish_forbidden", "publish protection"],
  [worker, "debug_context_json", "worker debug context loading"],
  [router, "skill_debug_targeted_override", "targeted override trace"],
  [frontend, "调试 Skill", "binding debug entry"],
  [frontend, "严格生产路由", "production route UI"],
  [frontend, "Skill 调试工作台", "workbench UI"]
];

const failures = checks.filter(([source, snippet]) => !source.includes(snippet)).map(([, , label]) => label);
if (failures.length) throw new Error(`skill debug workbench verification failed:\n${failures.join("\n")}`);
console.log(JSON.stringify({ ok: true, verified: "skill_debug_workbench" }, null, 2));
