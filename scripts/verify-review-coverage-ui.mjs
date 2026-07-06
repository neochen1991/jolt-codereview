import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const reviewViewsPath = path.join(root, "frontend", "src", "frontend", "components", "ReviewViews.tsx");
const source = readFileSync(reviewViewsPath, "utf8");

const requiredSnippets = [
  "bound_review_coverage",
  "resolution_rate",
  "unresolved_count",
  "required_count",
  "绑定规则闭环",
  "未闭环规则",
  "formatCoveragePercent"
];

const missing = requiredSnippets.filter((snippet) => !source.includes(snippet));
if (missing.length) {
  throw new Error(`review coverage UI is missing snippets: ${missing.join(", ")}`);
}

console.log(JSON.stringify({ ok: true, verified: "review_coverage_ui", snippets: requiredSnippets.length }));
