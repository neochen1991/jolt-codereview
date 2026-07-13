import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(import.meta.dirname, "..");
const runtimePath = path.join(ROOT, "mr-backend", "worker", "review_runtime.py");
const runtime = fs.readFileSync(runtimePath, "utf8");

const expectedPriority = "CASE WHEN queued.execution_kind = 'production_review' THEN 0 ELSE 1 END";
const expectedAgeOrder = "queued_mr.created_at ASC, queued.created_at ASC";

if (!runtime.includes(expectedPriority)) {
  throw new Error(`worker must reserve queue priority for production reviews: missing "${expectedPriority}"`);
}

if (!runtime.includes(expectedAgeOrder)) {
  throw new Error(`worker must claim jobs of the same class by MR created_at first: missing "${expectedAgeOrder}"`);
}

const priorityOrder = "ORDER BY queued.priority DESC, queued.created_at ASC";
if (runtime.includes(priorityOrder)) {
  throw new Error("worker still prioritizes risk score before MR created_at");
}

console.log(JSON.stringify({
  ok: true,
  expected_priority: expectedPriority,
  expected_age_order: expectedAgeOrder
}, null, 2));
