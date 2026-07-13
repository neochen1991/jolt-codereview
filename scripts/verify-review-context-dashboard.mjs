import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const routeSource = readFileSync(resolve(root, "mr-backend/src/backend/routes/review.routes.ts"), "utf8");
const uiSource = readFileSync(resolve(root, "frontend/src/frontend/components/ReviewViews.tsx"), "utf8");
const config = JSON.parse(readFileSync(resolve(root, "config.json"), "utf8"));

const apiFields = [
  "context_health",
  "candidate_recall",
  "verify_rejection_reasons",
  "judge_rejection_reasons",
  "published_precision",
  "skill_checkpoint_metrics",
  "reproducibility",
  "unresolved_candidates"
];
for (const field of apiFields) {
  if (!routeSource.includes(field)) throw new Error(`review quality API missing ${field}`);
}
for (const label of ["Context Health", "Quality Funnel", "Skill Checkpoint", "Reproducibility", "未闭环 Candidate"]) {
  if (!uiSource.includes(label)) throw new Error(`review quality UI missing ${label}`);
}
for (const status of ["full", "partial", "patch_only", "blocked"]) {
  if (!uiSource.includes(status)) throw new Error(`context health UI missing explicit status ${status}`);
}
const quality = config.review_quality || {};
const allowed = {
  context_engine: new Set(["v1", "v2"]),
  semantic_index: new Set(["regex", "tree_sitter", "typed"]),
  llm_replay: new Set(["off", "record", "replay", "live_repeat"])
};
for (const [key, values] of Object.entries(allowed)) {
  if (!values.has(quality[key])) throw new Error(`invalid review_quality.${key}`);
}

console.log(JSON.stringify({ ok: true, verified: "review_context_dashboard", api_fields: apiFields.length }));
