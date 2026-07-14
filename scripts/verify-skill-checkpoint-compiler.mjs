import assert from "node:assert/strict";

const { compileSkillCheckpointManifest } = await import("../mr-backend/build/backend/services/SkillCheckpointCompiler.js");

const explicit = compileSkillCheckpointManifest("secure-review", [{
  asset_path: "SKILL.md",
  content: `---\nname: secure-review\ndescription: 安全检查\n---\n\n## SEC-CMD-001 命令执行\n- severity: high\n- applies_to: src/**/*.ts\n- check: 禁止拼接命令。\n- required_evidence: 指出命令来源和调用行。\n- false_positive_patterns: 参数来自固定枚举。\n- fix_guidance: 使用参数数组。\n`
}]);
assert.equal(explicit.ok, false);
assert.ok(explicit.diagnostics.some((item) => item.code === "missing_checkpoint_field" && item.message.includes("negative_examples")));
assert.ok(explicit.diagnostics.some((item) => item.code === "missing_checkpoint_field" && item.message.includes("skip_conditions")));

const explicitWithCounterexamples = compileSkillCheckpointManifest("secure-review", [{
  asset_path: "SKILL.md",
  content: `---\nname: secure-review\ndescription: 安全检查\n---\n\n## SEC-CMD-001 命令执行\n- severity: high\n- applies_to: src/**/*.ts\n- check: 禁止拼接命令。\n- required_evidence: 指出命令来源和调用行。\n- false_positive_patterns: 参数来自固定枚举。\n- negative_examples: 仅执行固定维护脚本且参数不来自请求。\n- skip_conditions: 测试代码、demo 或命令来自不可变 allowlist。\n- fix_guidance: 使用参数数组。\n`
}]);
assert.equal(explicitWithCounterexamples.ok, true, JSON.stringify(explicitWithCounterexamples.diagnostics));
assert.equal(explicitWithCounterexamples.checkpoints[0].checkpoint_id, "SEC-CMD-001");
assert.equal(explicitWithCounterexamples.checkpoints[0].source_line_start, 6);
assert.equal(explicitWithCounterexamples.checkpoints[0].evidence_scope, "symbol");
assert.equal(explicitWithCounterexamples.checkpoints[0].max_dependency_hops, 1);
assert.equal(explicitWithCounterexamples.checkpoints[0].skip_conditions, "测试代码、demo 或命令来自不可变 allowlist。");

const crossFile = compileSkillCheckpointManifest("cross-file-review", [{
  asset_path: "SKILL.md",
  content: `## AUTH-CROSS-001 跨文件鉴权检查
- check: 检查入口到服务的权限链路。
- required_evidence: 展示调用方与实现。
- false_positive_patterns: 统一网关已校验。
- negative_examples: Controller 已通过统一网关或注解完成鉴权。
- skip_conditions: 只读查询、测试桩或内部定时任务。
- fix_guidance: 增加服务端权限拦截。
- evidence_scope: cross_file
- context_queries: callers, implementations, tests
- max_dependency_hops: 2
`
}]);
assert.equal(crossFile.ok, true, JSON.stringify(crossFile.diagnostics));
assert.equal(crossFile.checkpoints[0].evidence_scope, "cross_file");
assert.deepEqual(crossFile.checkpoints[0].context_queries, ["callers", "implementations", "tests"]);
assert.equal(crossFile.checkpoints[0].max_dependency_hops, 2);

const invalidContext = compileSkillCheckpointManifest("invalid-context", [{
  asset_path: "SKILL.md",
  content: `## BAD-CTX-001 非法查询
- check: test
- required_evidence: test
- false_positive_patterns: test
- negative_examples: test
- skip_conditions: test
- fix_guidance: test
- context_queries: internet_search
- max_dependency_hops: 8
`
}]);
assert.equal(invalidContext.ok, false);
assert.ok(invalidContext.diagnostics.some((item) => item.code === "invalid_context_query"));
assert.ok(invalidContext.diagnostics.some((item) => item.code === "invalid_max_dependency_hops"));

const sectionStyle = compileSkillCheckpointManifest("section-review", [{
  asset_path: "SKILL.md",
  content: `## SEC-SECTION-001 分章节检查\n- severity: high\n- applies_to: **/*.java\n\n### 如何检查\n禁止直接执行请求中的命令。\n\n### 证据要求\n展示请求参数到执行点的数据流。\n\n### 误报排除\n命令来自固定枚举。\n\n### 反例\n维护脚本使用固定命令。\n\n### 跳过条件\n测试代码或 demo。\n\n### 修复建议\n改用参数数组。\n`
}]);
assert.equal(sectionStyle.ok, true, JSON.stringify(sectionStyle.diagnostics));
assert.equal(sectionStyle.checkpoints[0].check, "禁止直接执行请求中的命令。");
assert.equal(sectionStyle.checkpoints[0].required_evidence, "展示请求参数到执行点的数据流。");

const natural = compileSkillCheckpointManifest("refund-risk", [{
  asset_path: "references/rules.md",
  content: `# 退款风险\n\n## 检查点\n\n### 金额必须使用可信订单数据\n- id: REFUND-AMOUNT-001\n- 严重级别: high\n- 适用范围: src/**/*.java\n- 如何检查: 禁止直接采用请求金额。\n- 证据要求: 展示请求金额流向。\n- 误报排除: 金额由订单服务重新加载。\n- 反例: 金额字段只用于日志展示。\n- 跳过条件: 只读查询或测试代码。\n- 修复建议: 从订单快照读取金额。\n`
}]);
assert.equal(natural.ok, true, JSON.stringify(natural.diagnostics));
assert.equal(natural.checkpoints[0].checkpoint_id, "REFUND-AMOUNT-001");
assert.equal(natural.checkpoints[0].check, "禁止直接采用请求金额。");

const table = compileSkillCheckpointManifest("db-review", [{
  asset_path: "references/db.md",
  content: `| checkpoint_id | title | check | required_evidence | false_positive_patterns | negative_examples | skip_conditions | fix_guidance |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n| DB-001 | 查询必须有上限 | 检查分页或 limit | 展示查询构造代码 | 已由框架注入上限 | 框架分页插件统一注入 limit | 测试夹具或只读 explain | 增加分页 |`
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
  content: `## Checkpoints\n### 禁止吞掉异常\n- check: catch 后必须处理或重新抛出。\n- required_evidence: 展示 catch 块。\n- false_positive_patterns: 明确记录并转换异常。\n- negative_examples: catch 后记录完整上下文并返回安全降级值。\n- skip_conditions: 测试代码或 intentionally ignored cleanup。\n- fix_guidance: 重新抛出领域异常。\n`
}]);
const generatedB = compileSkillCheckpointManifest("coding", [{
  asset_path: "references/style.md",
  content: `## Checkpoints\n### 禁止吞掉异常\n正文发生变化。\n- check: catch 后必须处理或重新抛出。\n- required_evidence: 展示 catch 块。\n- false_positive_patterns: 明确记录并转换异常。\n- negative_examples: catch 后记录完整上下文并返回安全降级值。\n- skip_conditions: 测试代码或 intentionally ignored cleanup。\n- fix_guidance: 重新抛出领域异常。\n`
}]);
assert.equal(generatedA.checkpoints[0].checkpoint_id, generatedB.checkpoints[0].checkpoint_id);
assert.match(generatedA.checkpoints[0].checkpoint_id, /^CODING-AUTO-/);

const duplicate = compileSkillCheckpointManifest("dup", [{
  asset_path: "SKILL.md",
  content: `## DUP-001 一\n- check: a\n- required_evidence: a\n- false_positive_patterns: a\n- negative_examples: a\n- skip_conditions: a\n- fix_guidance: a\n\n## DUP-001 二\n- check: b\n- required_evidence: b\n- false_positive_patterns: b\n- negative_examples: b\n- skip_conditions: b\n- fix_guidance: b\n`
}]);
assert.equal(duplicate.ok, false);
assert.ok(duplicate.diagnostics.some((item) => item.code === "duplicate_checkpoint_id"));

console.log(JSON.stringify({ ok: true, verified: "skill_checkpoint_compiler" }, null, 2));
