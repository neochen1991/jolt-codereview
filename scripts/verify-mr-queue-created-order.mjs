import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(import.meta.dirname, "..");
const runtimePath = path.join(ROOT, "mr-backend", "worker", "review_runtime.py");
const runtime = fs.readFileSync(runtimePath, "utf8");

const expectedOrder = "ORDER BY queued_mr.created_at ASC, queued.created_at ASC";

if (!runtime.includes(expectedOrder)) {
  throw new Error(`worker must claim queued MR jobs by MR created_at first: missing "${expectedOrder}"`);
}

const priorityOrder = "ORDER BY queued.priority DESC, queued.created_at ASC";
if (runtime.includes(priorityOrder)) {
  throw new Error("worker still prioritizes risk score before MR created_at");
}

console.log(JSON.stringify({ ok: true, expected_order: expectedOrder }, null, 2));
