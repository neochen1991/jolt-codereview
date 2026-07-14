import { readdirSync, readFileSync, statSync } from "node:fs";
import { extname, join, relative, resolve } from "node:path";

const root = resolve(".");
const self = "scripts/verify-v2-only-review-engine.mjs";
const sourceRoots = [
  "mr-backend/worker",
  "mr-backend/src",
  "common-backend/src",
  "frontend/src",
  "scripts",
];
const rootFiles = ["README.md", "package.json"];
const extensions = new Set([".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".md"]);
const ignoredDirectories = new Set(["build", "dist", "node_modules", ".venv", "__pycache__"]);
const forbidden = [
  'context_engine == "v1"',
  "quality_shadow_v1",
  "quality_shadow_v2",
  "enqueue_v1_shadow_pair",
  "evaluate_and_request_runtime_rollback",
  "v1_rolled_back",
  "rollback_pending",
  "verify:review-quality-shadow",
  "verify:review-quality-rollback",
];

function collect(path) {
  const absolute = resolve(path);
  if (statSync(absolute).isFile()) return [relative(root, absolute)];
  return readdirSync(absolute, { withFileTypes: true }).flatMap((entry) => {
    if (entry.isDirectory() && ignoredDirectories.has(entry.name)) return [];
    const child = join(absolute, entry.name);
    if (entry.isDirectory()) return collect(child);
    if (!extensions.has(extname(entry.name))) return [];
    return [relative(root, child)];
  });
}

const files = [...new Set([...sourceRoots.flatMap(collect), ...rootFiles])]
  .filter((path) => path !== self)
  .sort();
const failures = [];

for (const path of files) {
  const content = readFileSync(resolve(path), "utf8");
  const lines = content.split(/\r?\n/u);
  for (const token of forbidden) {
    lines.forEach((line, index) => {
      if (line.includes(token)) failures.push(`${path}:${index + 1}: ${token}`);
    });
  }
}

if (failures.length > 0) {
  throw new Error(`v2-only review engine verification failed:\n${failures.join("\n")}`);
}

console.log(JSON.stringify({ ok: true, verified: "v2_only_review_engine", files_scanned: files.length }));
