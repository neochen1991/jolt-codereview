import { existsSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { loadConfig, root } from "./config-utils.mjs";

const dryRun = !process.argv.includes("--apply");
const commonConfigPath = path.resolve(process.env.COMMON_CONFIG_PATH || path.join(root, "common-backend", "config.json"));
const mrConfigPath = path.resolve(process.env.MR_CONFIG_PATH || path.join(root, "mr-backend", "config.json"));
const commonExamplePath = path.join(root, "common-backend", "config.example.json");
const mrExamplePath = path.join(root, "mr-backend", "config.example.json");

async function importBuilt(relativePath) {
  const absolutePath = path.join(root, relativePath);
  if (!existsSync(absolutePath)) {
    throw new Error(`Build output not found: ${absolutePath}. Run npm run build first.`);
  }
  return import(pathToFileURL(absolutePath).href);
}

function summarize(label, serviceRoot, result) {
  return {
    service: label,
    dry_run: result.dry_run,
    scanned: result.scanned,
    candidates: result.candidates.map((item) => ({
      path: path.relative(serviceRoot, item.path),
      kind: item.kind,
      reason: item.reason,
      size_bytes: item.size_bytes
    })),
    deleted: result.deleted.map((item) => ({
      path: path.relative(serviceRoot, item.path),
      kind: item.kind,
      reason: item.reason,
      size_bytes: item.size_bytes
    })),
    skipped: result.skipped.map((item) => ({ ...item, path: path.relative(serviceRoot, item.path) })),
    errors: result.errors.map((item) => ({ ...item, path: path.relative(serviceRoot, item.path) }))
  };
}

const commonConfig = loadConfig(commonConfigPath, commonExamplePath);
const mrConfig = loadConfig(mrConfigPath, mrExamplePath);
const commonRoot = path.join(root, "common-backend");
const mrRoot = path.join(root, "mr-backend");
const { runRuntimeFileCleanup: runCommonCleanup } = await importBuilt("common-backend/build/backend/services/RuntimeFileCleanupService.js");
const { runRuntimeFileCleanup: runMrCleanup } = await importBuilt("mr-backend/build/backend/services/RuntimeFileCleanupService.js");

const results = [
  summarize("common-backend", commonRoot, runCommonCleanup(commonConfig, { serviceRoot: commonRoot, dryRun })),
  summarize("mr-backend", mrRoot, runMrCleanup(mrConfig, { serviceRoot: mrRoot, dryRun }))
];

console.log(JSON.stringify({
  ok: results.every((result) => result.errors.length === 0),
  mode: dryRun ? "dry-run" : "apply",
  hint: dryRun ? "Run npm run cleanup:runtime -- --apply to delete these files." : "Runtime cleanup applied.",
  results
}, null, 2));

if (results.some((result) => result.errors.length > 0)) {
  process.exitCode = 1;
}
