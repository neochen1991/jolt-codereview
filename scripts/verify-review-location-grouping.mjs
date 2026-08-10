import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const { groupFindingsByLocation, formatLocationGroupBody } = await import(
  path.join(root, "mr-backend", "build", "backend", "reviewLocationGrouping.js")
);

const findings = [
  {
    id: "sql",
    severity: "high",
    file_path: "src/QueryService.java",
    line_start: 25,
    line_end: 25,
    title: "SQL 注入",
    problem_description: "SQL 直接拼接输入。",
    recommendation: "使用参数绑定。",
    suggested_code: "query(sql, value);"
  },
  {
    id: "limit",
    severity: "medium",
    file_path: "src/QueryService.java",
    line_start: 25,
    line_end: 25,
    title: "查询无上限",
    problem_description: "查询没有分页。",
    recommendation: "增加 limit。",
    suggested_code: "query.limit(100);"
  },
  {
    id: "auth",
    severity: "high",
    file_path: "src/AuthService.java",
    line_start: 9,
    line_end: 9,
    title: "缺少鉴权",
    problem_description: "更新前未鉴权。",
    recommendation: "增加鉴权。",
    suggested_code: "authorize();"
  }
];

const groups = groupFindingsByLocation(findings);
assert.equal(groups.length, 2);
assert.equal(groups.find((group) => group.key === "src/QueryService.java:25")?.findings.length, 2);

const markdown = formatLocationGroupBody(findings, "github");
assert.equal((markdown.match(/位置：src\/QueryService\.java:25/g) || []).length, 1);
assert.match(markdown, /1\. \[high\] SQL 注入/);
assert.match(markdown, /2\. \[medium\] 查询无上限/);

const review = readFileSync(path.join(root, "frontend", "src", "frontend", "components", "ReviewViews.tsx"), "utf8");
const shared = readFileSync(path.join(root, "frontend", "src", "frontend", "shared.ts"), "utf8");
assert.match(shared, /export function groupFindingsByLocation/);
assert.match(review, /groupFindingsByLocation\(sortedFindings\)/);
assert.match(review, /className="finding-location-group"/);

console.log(JSON.stringify({ ok: true, groups: groups.length, findings: findings.length }));
