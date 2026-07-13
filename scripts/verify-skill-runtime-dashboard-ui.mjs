import { readFileSync } from "node:fs";

const source = readFileSync("frontend/src/frontend/components/ProjectViews.tsx", "utf8");
const styles = readFileSync("frontend/src/frontend/styles.css", "utf8");
const required = [
  "/api/projects/${project.id}/skill-runtime/dashboard",
  "适用路由率",
  "全量路由率",
  "加载率",
  "Checkpoint 完成率",
  "未闭环率",
  "命中率",
  "误报率",
  "反馈覆盖率",
  "judge_unclassified_rejection",
  "legacy_skill_runtime_data",
  "skill-runtime-kpi-grid"
];
const failures = required.filter((item) => !source.includes(item) && !styles.includes(item));
if (failures.length) throw new Error(`Skill runtime dashboard UI missing:\n${failures.join("\n")}`);
console.log(JSON.stringify({ ok: true, verified: "skill_runtime_dashboard_ui" }, null, 2));
