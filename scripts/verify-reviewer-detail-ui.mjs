import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (...parts) => readFileSync(path.join(root, ...parts), "utf8");
const shared = read("frontend", "src", "frontend", "shared.ts");
const app = read("frontend", "src", "frontend", "App.tsx");
const review = read("frontend", "src", "frontend", "components", "ReviewViews.tsx");

assert.match(shared, /diagnostics_visible\?: boolean/);
assert.match(shared, /has_review_run\?: boolean/);
assert.match(app, /canViewDiagnostics=\{canManageProject\}/);
assert.match(review, /canViewDiagnostics: boolean/);
assert.match(review, /const showDiagnostics = Boolean\(detail && canViewDiagnostics && detail\.diagnostics_visible !== false\)/);
assert.match(review, /if \(!showDiagnostics && tab !== "findings"\) setTab\("findings"\)/);
assert.match(review, /\{showDiagnostics && \(\s*<div className="detail-tabs">[\s\S]*\["process", "检视过程"\]/);
assert.match(review, /showDiagnostics && hasRun && <CoverageCard/);
assert.match(review, /showDiagnostics && hasRun && <ReviewQualityCard/);
assert.match(review, /<ReviewProgressPanel[\s\S]*showDiagnostics=\{showDiagnostics\}/);
assert.match(review, /showDiagnostics && \([\s\S]*className="review-progress-meta"/);
assert.match(review, /showDiagnostics=\{showDiagnostics\}[\s\S]*onToggle=/);
assert.match(review, /showDiagnostics && <span className="agent-pill">/);
assert.match(review, /showDiagnostics && <span className=\{`finding-source-tag/);
assert.match(review, /showDiagnostics && \([\s\S]*<span>质量追溯<\/span>/);
assert.match(review, /showDiagnostics && \([\s\S]*<span>工具证据<\/span>/);
assert.match(review, /if \(!showDiagnostics\) \{\s*setRuleDetails\(ruleIds\.map/);
assert.match(review, /onFalsePositive=\{\(\) => onFalsePositive\(finding\)\}/);
assert.match(review, /onExportMarkdown/);
assert.match(review, /onRerun/);
assert.match(review, /onPublish/);

console.log(JSON.stringify({ ok: true, verified: "reviewer_detail_ui" }, null, 2));
