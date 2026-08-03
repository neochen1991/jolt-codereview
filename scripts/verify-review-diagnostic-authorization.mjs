import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (...parts) => readFileSync(path.join(root, ...parts), "utf8");
const routes = read("mr-backend", "src", "backend", "routes", "review.routes.ts");

const detailStart = routes.indexOf('route("GET", "/api/mr-review/merge-requests/:mrId"');
const detailEnd = routes.indexOf('route("DELETE", "/api/mr-review/merge-requests/:mrId"', detailStart);
const detailRoute = routes.slice(detailStart, detailEnd);

assert.match(routes, /function ensureRunDiagnostics/);
assert.match(routes, /function ensureMrDiagnostics/);
assert.match(routes, /reviewDetailVisibility/);
assert.match(detailRoute, /diagnostics_visible: diagnosticsVisible/);
assert.match(detailRoute, /has_review_run: Boolean\(latestRun\)/);
assert.match(detailRoute, /jobs: diagnosticsVisible \? jobs : \[\]/);
assert.match(detailRoute, /runs: diagnosticsVisible \? runs : \[\]/);
assert.match(detailRoute, /tool_observations: diagnosticsVisible \? toolObservations : \[\]/);
assert.match(detailRoute, /trace: diagnosticsVisible \? trace : \[\]/);
assert.match(detailRoute, /quality: diagnosticsVisible \? reviewQualityForRun/);
assert.match(detailRoute, /diagnosticsVisible \? compareRunsForMr/);
assert.match(detailRoute, /diagnosticsVisible && latestRun/);

for (const routePath of [
  "/api/mr-review/review-runs/:runId",
  "/api/mr-review/review-runs/:runId/trace",
  "/api/mr-review/review-runs/:runId/session-logs",
  "/api/mr-review/review-runs/:runId/skill-trace",
  "/api/mr-review/review-runs/:runId/artifacts"
]) {
  const start = routes.indexOf(`route("GET", "${routePath}"`);
  const body = routes.slice(start, routes.indexOf("}),", start) + 3);
  assert.ok(start >= 0, `missing ${routePath}`);
  assert.match(body, /ensureRunDiagnostics/, `${routePath} must require admin diagnostics access`);
}

for (const routePath of [
  "/api/mr-review/merge-requests/:mrId/logs",
  "/api/mr-review/merge-requests/:mrId/review-runs/compare"
]) {
  const start = routes.indexOf(`route("GET", "${routePath}"`);
  const body = routes.slice(start, routes.indexOf("}),", start) + 3);
  assert.ok(start >= 0, `missing ${routePath}`);
  assert.match(body, /ensureMrDiagnostics|project_admin/, `${routePath} must require admin diagnostics access`);
}

assert.match(routes, /ensureProjectRole\(repo\.project_id, actorId, "reviewer"\)/);

console.log(JSON.stringify({ ok: true, verified: "review_diagnostic_authorization" }, null, 2));
