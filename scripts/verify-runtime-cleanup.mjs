import assert from "node:assert/strict";
import { mkdirSync, readFileSync, utimesSync, writeFileSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const root = path.resolve(import.meta.dirname, "..");
const tmpRoot = await mkdtemp(path.join(tmpdir(), "jolt-runtime-cleanup-"));

function touchOld(filePath, daysAgo) {
  const date = new Date(Date.now() - daysAgo * 24 * 60 * 60 * 1000);
  utimesSync(filePath, date, date);
}

function writeFixture(filePath, content = "fixture\n", daysAgo = 0) {
  mkdirSync(path.dirname(filePath), { recursive: true });
  writeFileSync(filePath, content, "utf8");
  if (daysAgo > 0) touchOld(filePath, daysAgo);
}

async function importBuilt(relativePath) {
  return import(pathToFileURL(path.join(root, relativePath)).href);
}

try {
  const mrServiceRoot = path.join(tmpRoot, "mr-backend");
  const commonServiceRoot = path.join(tmpRoot, "common-backend");
  const oldSandbox = path.join(mrServiceRoot, "worker", "data", "sandboxes", "run_old");
  const freshSandbox = path.join(mrServiceRoot, "worker", "data", "sandboxes", "run_fresh");
  mkdirSync(oldSandbox, { recursive: true });
  mkdirSync(freshSandbox, { recursive: true });
  writeFixture(path.join(oldSandbox, "artifact.json"), "{}", 3);
  writeFixture(path.join(freshSandbox, "artifact.json"), "{}", 0);
  touchOld(oldSandbox, 3);
  writeFixture(path.join(mrServiceRoot, "logs", "review-runs", "run_old.jsonl"), "old\n", 3);
  writeFixture(path.join(mrServiceRoot, "logs", "review-runs", "run_fresh.jsonl"), "fresh\n", 0);
  writeFixture(path.join(mrServiceRoot, "logs", "jolt-worker.log"), "old worker\n", 3);
  writeFixture(path.join(mrServiceRoot, "logs", "jolt-api.log"), "x".repeat(2048), 0);
  writeFixture(path.join(mrServiceRoot, "config", "static-rules", "keep.yaml"), "rule\n", 3);

  writeFixture(path.join(commonServiceRoot, "logs", "jolt-common-api.log"), "old common\n", 3);
  writeFixture(path.join(commonServiceRoot, "README.md"), "keep\n", 3);

  const { runRuntimeFileCleanup: runMrCleanup } = await importBuilt("mr-backend/build/backend/services/RuntimeFileCleanupService.js");
  const { runRuntimeFileCleanup: runCommonCleanup } = await importBuilt("common-backend/build/backend/services/RuntimeFileCleanupService.js");

  const policy = {
    enabled: true,
    max_age_days: 1,
    max_total_mb: 1,
    max_log_file_mb: 0.001,
    run_on_startup: true,
    interval_seconds: 3600
  };

  const mrDryRun = runMrCleanup({ logging: { enabled: true, dir: "logs", api_file: "jolt-api.log", worker_file: "jolt-worker.log", review_run_dir: "review-runs" }, cleanup_policy: policy }, { serviceRoot: mrServiceRoot, dryRun: true });
  assert.equal(mrDryRun.deleted.length, 0, "dry-run must not delete files");
  assert(mrDryRun.candidates.some((item) => item.path.endsWith(path.join("sandboxes", "run_old"))), "old sandbox must be a cleanup candidate");
  assert(mrDryRun.candidates.some((item) => item.path.endsWith(path.join("review-runs", "run_old.jsonl"))), "old review-run log must be a cleanup candidate");
  assert(mrDryRun.candidates.some((item) => item.path.endsWith("jolt-worker.log")), "old worker log must be a cleanup candidate");
  assert(mrDryRun.candidates.some((item) => item.path.endsWith("jolt-api.log") && item.reason === "max_log_size"), "oversized fresh API log must be a cleanup candidate");

  const mrResult = runMrCleanup({ logging: { enabled: true, dir: "logs", api_file: "jolt-api.log", worker_file: "jolt-worker.log", review_run_dir: "review-runs" }, cleanup_policy: policy }, { serviceRoot: mrServiceRoot });
  assert(mrResult.deleted.length >= 3, "MR cleanup must delete old runtime files");
  assert.throws(() => readFileSync(path.join(oldSandbox, "artifact.json"), "utf8"), /ENOENT/, "old sandbox must be removed");
  assert.throws(() => readFileSync(path.join(mrServiceRoot, "logs", "jolt-api.log"), "utf8"), /ENOENT/, "oversized API log must be removed");
  assert.equal(readFileSync(path.join(freshSandbox, "artifact.json"), "utf8"), "{}", "fresh sandbox must remain");
  assert.equal(readFileSync(path.join(mrServiceRoot, "config", "static-rules", "keep.yaml"), "utf8"), "rule\n", "static rule files must remain");

  const commonResult = runCommonCleanup({ logging: { enabled: true, dir: "logs", api_file: "jolt-common-api.log" }, cleanup_policy: policy }, { serviceRoot: commonServiceRoot });
  assert(commonResult.deleted.some((item) => item.path.endsWith("jolt-common-api.log")), "Common cleanup must delete old API log");
  assert.equal(readFileSync(path.join(commonServiceRoot, "README.md"), "utf8"), "keep\n", "Common non-runtime files must remain");

  console.log(JSON.stringify({
    ok: true,
    mr_deleted: mrResult.deleted.map((item) => path.relative(mrServiceRoot, item.path)),
    common_deleted: commonResult.deleted.map((item) => path.relative(commonServiceRoot, item.path))
  }, null, 2));
} finally {
  await rm(tmpRoot, { recursive: true, force: true });
}
