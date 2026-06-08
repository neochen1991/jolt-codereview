import { readFileSync } from "node:fs";
import { formatMrReviewMarkdown } from "../build/backend/reviewMarkdown.js";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const markdown = formatMrReviewMarkdown({
  mr: {
    id: "mr_1",
    repository_name: "payment-service",
    provider: "codehub",
    number: 284,
    title: "修复项目权限更新接口",
    author: "陈旭",
    source_branch: "feat/project-setting",
    target_branch: "master",
    review_status: "waiting_confirmation",
    risk_score: 86,
    latest_head_sha: "abc123",
    html_url: "https://codehub.example.com/payment-service/merge_requests/284"
  },
  run: {
    id: "run_1",
    status: "waiting_confirmation",
    effort_level: "standard",
    report_summary: "发现 1 个高危问题",
    started_at: "2026-06-07 10:20",
    completed_at: "2026-06-07 10:25"
  },
  findings: [
    {
      id: "finding_1",
      review_run_id: "run_1",
      severity: "high",
      confidence: 0.92,
      agent_id: "security_agent",
      head_sha: "abc123",
      dedupe_hash: "hash_1",
      file_path: "backend/api/project.py",
      line_start: 88,
      line_end: 88,
      title: "缺少项目管理员权限校验",
      problem_description: "项目配置更新接口没有校验操作者是否具备 project_admin 权限。",
      recommendation: "在更新前校验当前用户是否具备项目管理员角色。",
      suggested_code: "if (!currentUser.hasRole(\"project_admin\")) {\n  throw new AccessDeniedException(\"project_admin required\");\n}",
      evidence: "updateProjectSettings(request);",
      covered_rules_json: "[\"SEC-AUTH-001\"]",
      skipped_rules_json: "[\"SEC-SECRET-004\"]",
      tool_provenance_json: "[{\"tool_name\":\"semgrep\",\"rule_id\":\"SEC-AUTH-001\",\"confidence\":0.91}]",
      source_observations_json: "[{\"tool_name\":\"semgrep\",\"rule_id\":\"SEC-AUTH-001\",\"message\":\"missing authorization check\",\"file_path\":\"backend/api/project.py\",\"line_start\":88,\"confidence\":0.91}]",
      quality_trace_json: "{\"agent_id\":\"security_agent\",\"dedupe_hash\":\"hash_1\"}",
      publish_state: "pending",
      lifecycle_state: "pending",
      selected: 1
    }
  ]
});

for (const expected of [
  "# Jolt CodeReview 检视报告",
  "!284 修复项目权限更新接口",
  "payment-service",
  "## 问题总览",
  "## 问题详情",
  "### 1. [高危] 缺少项目管理员权限校验",
  "**位置**：`backend/api/project.py:88`",
  "**检视专家**：Security Agent",
  "**置信度**：0.92",
  "**命中规范**：`SEC-AUTH-001`",
  "#### 工具证据",
  "semgrep",
  "missing authorization check",
  "```python",
  "updateProjectSettings(request);",
  "```",
  "```python",
  "throw new AccessDeniedException",
  "```"
]) {
  assert(markdown.includes(expected), `markdown missing: ${expected}`);
}

const frontend = readFileSync("src/frontend/main.tsx", "utf-8");
assert(frontend.includes("/export.md"), "frontend must call markdown export endpoint");
assert(frontend.includes("导出 MD"), "frontend must expose export md button");
assert(frontend.includes("download = filename"), "frontend must trigger browser md download");

const routeSource = readFileSync("src/backend/routes/review.routes.ts", "utf-8");
assert(routeSource.includes("/api/mr-review/merge-requests/:mrId/export.md"), "backend route must expose markdown export endpoint");

console.log(JSON.stringify({ ok: true, markdown_length: markdown.length }, null, 2));
