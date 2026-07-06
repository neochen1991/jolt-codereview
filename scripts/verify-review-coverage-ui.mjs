import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const reviewViewsPath = path.join(root, "frontend", "src", "frontend", "components", "ReviewViews.tsx");
const configViewsPath = path.join(root, "frontend", "src", "frontend", "components", "ConfigViews.tsx");
const reviewSource = readFileSync(reviewViewsPath, "utf8");
const configSource = readFileSync(configViewsPath, "utf8");

const reviewSnippets = [
  "bound_review_coverage",
  "resolution_rate",
  "unresolved_count",
  "required_count",
  "alerts",
  "绑定规则闭环",
  "未闭环规则",
  "质量告警",
  "formatCoveragePercent"
];
const configSnippets = [
  "review-quality/metrics",
  "projectBoundRuleCoverage",
  "bound_rule_coverage",
  "bound_rule_resolution_rate",
  "bound_rule_unresolved_count",
  "项目规则闭环",
  "规则闭环",
  "未闭环"
];

const missing = [
  ...reviewSnippets.filter((snippet) => !reviewSource.includes(snippet)).map((snippet) => `ReviewViews:${snippet}`),
  ...configSnippets.filter((snippet) => !configSource.includes(snippet)).map((snippet) => `ConfigViews:${snippet}`)
];
if (missing.length) {
  throw new Error(`review coverage UI is missing snippets: ${missing.join(", ")}`);
}

console.log(JSON.stringify({ ok: true, verified: "review_coverage_ui", snippets: reviewSnippets.length + configSnippets.length }));
