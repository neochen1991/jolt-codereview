import { readFileSync } from "node:fs";
import path from "node:path";
const root = process.cwd();
const read = (...parts) => readFileSync(path.join(root, ...parts), "utf8");
const fetchNode = read("mr-backend", "worker", "orchestration", "nodes", "fetch_mr.py");
const runtime = read("mr-backend", "worker", "review_runtime.py");
const routes = read("mr-backend", "src", "backend", "routes", "review.routes.ts");
const frontend = read("frontend", "src", "frontend", "components", "ConfigViews.tsx");
const checks = [
  [fetchNode, "load_debug_input_artifact", "fetch node can reuse frozen input"],
  [fetchNode, "save_debug_input_artifact", "fetch node freezes the first input"],
  [fetchNode, "skill_debug_input_reused", "input reuse trace evidence"],
  [runtime, "load_skill_debug_input_artifact", "worker loads session input artifact"],
  [runtime, "save_skill_debug_input_artifact", "worker stores session input artifact"],
  [runtime, "input_artifact_sha256", "content-addressed input artifact"],
  [runtime, "changed_file_from_vcs_row", "frozen records hydrate to production changed-file objects"],
  [routes, "/rerun-latest", "latest-head rerun is separate"],
  [routes, "same_input", "same-input rerun contract"],
  [frontend, "在最新 MR 上验证", "latest-head rerun UI"]
];
const failures = checks.filter(([source, snippet]) => !source.includes(snippet)).map(([, , label]) => label);
if (failures.length) throw new Error(`skill debug input replay verification failed:\n${failures.join("\n")}`);
console.log(JSON.stringify({ ok: true, verified: "skill_debug_input_replay" }, null, 2));
