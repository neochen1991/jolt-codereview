import { readFileSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const routes = readFileSync(path.join(root, "mr-backend", "src", "backend", "routes", "review.routes.ts"), "utf8");
const worker = readFileSync(path.join(root, "mr-backend", "worker", "orchestration", "nodes", "run_experts.py"), "utf8");

const requiredRouteSnippets = [
  "/api/mr-review/review-runs/:runId/skill-trace",
  "buildSkillTracePayload",
  "bound_skill_started",
  "bound_skill_checked",
  "bound_batch_findings_rejected",
  "false_positive_matches",
  "missing_required_evidence",
  "judge_decisions",
  "decision_reason_json"
];

const requiredWorkerSnippets = [
  "\"rejected_items\"",
  "\"bound_evidence_contract\"",
  "\"rejected_reasons\"",
  "\"bound_batch_findings_rejected\""
];

const failures = [];
for (const snippet of requiredRouteSnippets) {
  if (!routes.includes(snippet)) failures.push(`review.routes.ts missing ${snippet}`);
}
for (const snippet of requiredWorkerSnippets) {
  if (!worker.includes(snippet)) failures.push(`run_experts.py missing ${snippet}`);
}

if (failures.length) {
  throw new Error(`skill trace API verification failed:\n${failures.join("\n")}`);
}

console.log(JSON.stringify({ ok: true, verified: "skill_trace_api" }, null, 2));
