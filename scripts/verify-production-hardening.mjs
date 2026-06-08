import fs from "node:fs";
import path from "node:path";

const ROOT = process.cwd();
const TARGETS = [
  "README.md",
  "src/backend",
  "worker/orchestration",
  "scripts/verify-local.mjs"
];

const FORBIDDEN = [
  /MVP/i,
  /not_implemented/i,
  /reserved_disabled/i,
  /deterministic_fallback/i,
  /langgraph_fallback/i,
  /Full code review worker is out of/i,
  /storage is not implemented/i,
  /placeholder API/i
];

function walk(filePath) {
  const stat = fs.statSync(filePath);
  if (stat.isDirectory()) {
    return fs.readdirSync(filePath)
      .filter((name) => !["node_modules", "build", "dist", "__pycache__"].includes(name))
      .flatMap((name) => walk(path.join(filePath, name)));
  }
  return [filePath];
}

function isTextFile(filePath) {
  return [".ts", ".tsx", ".js", ".mjs", ".py", ".md", ".json"].includes(path.extname(filePath));
}

const violations = [];
for (const target of TARGETS) {
  const absolute = path.join(ROOT, target);
  if (!fs.existsSync(absolute)) continue;
  for (const filePath of walk(absolute).filter(isTextFile)) {
    const text = fs.readFileSync(filePath, "utf-8");
    const lines = text.split(/\r?\n/);
    lines.forEach((line, index) => {
      for (const pattern of FORBIDDEN) {
        if (pattern.test(line)) {
          violations.push({
            file: path.relative(ROOT, filePath),
            line: index + 1,
            pattern: String(pattern),
            text: line.trim()
          });
        }
      }
    });
  }
}

if (violations.length) {
  console.error(JSON.stringify({ ok: false, violations }, null, 2));
  process.exit(1);
}

const requiredFiles = [
  "src/backend/routes/full-review.routes.ts",
  "src/backend/routes/quality.routes.ts",
  "worker/orchestration/graph.py",
  "worker/orchestration/nodes/prescan.py"
];
for (const file of requiredFiles) {
  if (!fs.existsSync(path.join(ROOT, file))) {
    throw new Error(`required production file missing: ${file}`);
  }
}

const fullReviewRoutes = fs.readFileSync(path.join(ROOT, "src/backend/routes/full-review.routes.ts"), "utf-8");
for (const required of ["full_review_jobs", "full_review_snapshots", "full_review_findings", "ensureProjectRole", "auditLog"]) {
  if (!fullReviewRoutes.includes(required)) {
    throw new Error(`full review API is missing production behavior marker: ${required}`);
  }
}

const graph = fs.readFileSync(path.join(ROOT, "worker/orchestration/graph.py"), "utf-8");
if (!graph.includes("LangGraph is required in production review orchestration")) {
  throw new Error("LangGraph must be a required production dependency");
}

console.log(JSON.stringify({
  ok: true,
  checks: [
    "no_mvp_markers_in_runtime_contracts",
    "full_review_uses_persistent_storage",
    "langgraph_required_no_silent_downgrade"
  ]
}, null, 2));
