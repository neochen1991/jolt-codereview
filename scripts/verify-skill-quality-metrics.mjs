import { readFileSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const service = readFileSync(path.join(root, "mr-backend", "src", "backend", "services", "ObservabilityService.ts"), "utf8");
const routes = readFileSync(path.join(root, "mr-backend", "src", "backend", "routes", "observability.routes.ts"), "utf8");
const projectViews = readFileSync(path.join(root, "frontend", "src", "frontend", "components", "ProjectViews.tsx"), "utf8");

const serviceSnippets = [
  "summarizeSkillCheckpointMetrics",
  "getSkillCheckpointQualityMetrics",
  "skill_key",
  "checkpoint_id",
  "retry_hit_count",
  "duplicate_merge_count",
  "manual_reject_count",
  "feedback_false_positive",
  "feedback_dismissed",
  "manual_reject_rate",
  "dimensions: [\"project_id\", \"skill_key\", \"checkpoint_id\", \"agent_id\", \"model\", \"week\"]"
];

const routeSnippets = [
  "/api/projects/:projectId/skill-checkpoints/quality",
  "getSkillCheckpointQualityMetrics"
];

const frontendSnippets = [
  "/api/projects/${project.id}/skill-checkpoints/quality",
  "skillQualityMetrics",
  "Skill Checkpoint 质量",
  "checkpoint_id",
  "人工误报",
  "manual_reject_rate",
  "retry_hit_rate"
];

const failures = [];
for (const snippet of serviceSnippets) {
  if (!service.includes(snippet)) failures.push(`ObservabilityService.ts missing ${snippet}`);
}
for (const snippet of routeSnippets) {
  if (!routes.includes(snippet)) failures.push(`observability.routes.ts missing ${snippet}`);
}
for (const snippet of frontendSnippets) {
  if (!projectViews.includes(snippet)) failures.push(`ProjectViews.tsx missing ${snippet}`);
}

if (failures.length) {
  throw new Error(`skill quality metrics verification failed:\n${failures.join("\n")}`);
}

console.log(JSON.stringify({ ok: true, verified: "skill_quality_metrics" }, null, 2));
