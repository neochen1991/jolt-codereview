import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const routes = readFileSync(resolve("common-backend/src/backend/routes/models.routes.ts"), "utf8");
const service = readFileSync(resolve("common-backend/src/backend/services/ProjectConfigService.ts"), "utf8");
const runtime = readFileSync(resolve("mr-backend/worker/review_runtime.py"), "utf8");
const rollback = readFileSync(resolve("mr-backend/worker/review_quality_rollback.py"), "utf8");

const checks = [
  [routes, 'POST", "/internal/models/projects/:projectId/review-quality/rollback', "internal rollback endpoint"],
  [routes, "ensureInternal(req)", "internal token guard"],
  [routes, "review_quality.auto_rollback", "rollback audit action"],
  [service, "rollbackReviewQuality", "narrow service mutation"],
  [service, 'context_engine: "v1"', "v1 rollback target"],
  [rollback, "rollback_pending", "durable pending state"],
  [runtime, "evaluate_and_request_runtime_rollback", "worker runtime rollback hook"]
];
const failures = checks.filter(([source, snippet]) => !source.includes(snippet)).map(([, , label]) => label);
if (failures.length) throw new Error(`review quality rollback API verification failed:\n${failures.join("\n")}`);
console.log(JSON.stringify({ ok: true, verified: "review_quality_rollback_api" }));
