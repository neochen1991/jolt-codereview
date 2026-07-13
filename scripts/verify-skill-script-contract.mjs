import { readFileSync } from "node:fs";
const routes = readFileSync("mr-backend/src/backend/routes/rules.routes.ts", "utf8");
const runner = readFileSync("mr-backend/worker/orchestration/deepagents_runner.py", "utf8");
const frontend = readFileSync("frontend/src/frontend/components/ConfigViews.tsx", "utf8");
const checks = [
  [routes, "non_executable_resource", "validation warning"],
  [routes, "executable: false", "server normalizes scripts to non-executable"],
  [runner, '"status": "blocked_by_policy"', "runtime blocks uploaded scripts"],
  [frontend, "只读脚本资源", "UI explains read-only script contract"]
];
const failures = checks.filter(([source, snippet]) => !source.includes(snippet)).map(([, , label]) => label);
if (failures.length) throw new Error(`skill script contract verification failed:\n${failures.join("\n")}`);
console.log(JSON.stringify({ ok: true, verified: "skill_script_contract" }, null, 2));
