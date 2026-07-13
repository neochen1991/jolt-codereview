import assert from "node:assert/strict";

const { compileSkillCheckpointManifest } = await import("../mr-backend/build/backend/services/SkillCheckpointCompiler.js");

const explicit = compileSkillCheckpointManifest("secure-review", [{
  asset_path: "SKILL.md",
  content: `---\nname: secure-review\ndescription: 安全检查\n---\n\n## SEC-CMD-001 命令执行\n- severity: high\n- applies_to: src/**/*.ts\n- check: 禁止拼接命令。\n- required_evidence: 指出命令来源和调用行。\n- false_positive_patterns: 参数来自固定枚举。\n- fix_guidance: 使用参数数组。\n`
}]);
assert.equal(explicit.ok, true, JSON.stringify(explicit.diagnostics));
assert.equal(explicit.checkpoints[0].checkpoint_id, "SEC-CMD-001");
assert.equal(explicit.checkpoints[0].source_line_start, 6);

const sectionStyle = compileSkillCheckpointManifest("section-review", [{
  asset_path: "SKILL.md",
  content: `## SEC-SECTION-001 分章节检查\n- severity: high\n- applies_to: **/*.java\n\n### 如何检查\n禁止直接执行请求中的命令。\n\n### 证据要求\n展示请求参数到执行点的数据流。\n\n### 误报排除\n命令来自固定枚举。\n\n### 修复建议\n改用参数数组。\n`
}]);
assert.equal(sectionStyle.ok, true, JSON.stringify(sectionStyle.diagnostics));
assert.equal(sectionStyle.checkpoints[0].check, "禁止直接执行请求中的命令。");
assert.equal(sectionStyle.checkpoints[0].required_evidence, "展示请求参数到执行点的数据流。");

const natural = compileSkillCheckpointManifest("refund-risk", [{
  asset_path: "references/rules.md",
  content: `# 退款风险\n\n## 检查点\n\n### 金额必须使用可信订单数据\n- id: REFUND-AMOUNT-001\n- 严重级别: high\n- 适用范围: src/**/*.java\n- 如何检查: 禁止直接采用请求金额。\n- 证据要求: 展示请求金额流向。\n- 误报排除: 金额由订单服务重新加载。\n- 修复建议: 从订单快照读取金额。\n`
}]);
assert.equal(natural.ok, true, JSON.stringify(natural.diagnostics));
assert.equal(natural.checkpoints[0].checkpoint_id, "REFUND-AMOUNT-001");
assert.equal(natural.checkpoints[0].check, "禁止直接采用请求金额。");

const table = compileSkillCheckpointManifest("db-review", [{
  asset_path: "references/db.md",
  content: `| checkpoint_id | title | check | required_evidence | false_positive_patterns | fix_guidance |\n| --- | --- | --- | --- | --- | --- |\n| DB-001 | 查询必须有上限 | 检查分页或 limit | 展示查询构造代码 | 已由框架注入上限 | 增加分页 |`
}]);
assert.equal(table.ok, true, JSON.stringify(table.diagnostics));
assert.equal(table.checkpoints[0].checkpoint_id, "DB-001");

const fenced = compileSkillCheckpointManifest("safe", [{
  asset_path: "SKILL.md",
  content: `# 示例\n\n\`\`\`markdown\n## FAKE-001 不应解析\n- check: fake\n\`\`\`\n`
}]);
assert.equal(fenced.checkpoints.length, 0);

const generatedA = compileSkillCheckpointManifest("coding", [{
  asset_path: "references/style.md",
  content: `## Checkpoints\n### 禁止吞掉异常\n- check: catch 后必须处理或重新抛出。\n- required_evidence: 展示 catch 块。\n- false_positive_patterns: 明确记录并转换异常。\n- fix_guidance: 重新抛出领域异常。\n`
}]);
const generatedB = compileSkillCheckpointManifest("coding", [{
  asset_path: "references/style.md",
  content: `## Checkpoints\n### 禁止吞掉异常\n正文发生变化。\n- check: catch 后必须处理或重新抛出。\n- required_evidence: 展示 catch 块。\n- false_positive_patterns: 明确记录并转换异常。\n- fix_guidance: 重新抛出领域异常。\n`
}]);
assert.equal(generatedA.checkpoints[0].checkpoint_id, generatedB.checkpoints[0].checkpoint_id);
assert.match(generatedA.checkpoints[0].checkpoint_id, /^CODING-AUTO-/);

const duplicate = compileSkillCheckpointManifest("dup", [{
  asset_path: "SKILL.md",
  content: `## DUP-001 一\n- check: a\n- required_evidence: a\n- false_positive_patterns: a\n- fix_guidance: a\n\n## DUP-001 二\n- check: b\n- required_evidence: b\n- false_positive_patterns: b\n- fix_guidance: b\n`
}]);
assert.equal(duplicate.ok, false);
assert.ok(duplicate.diagnostics.some((item) => item.code === "duplicate_checkpoint_id"));

console.log(JSON.stringify({ ok: true, verified: "skill_checkpoint_compiler" }, null, 2));
