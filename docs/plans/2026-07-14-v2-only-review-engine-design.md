# V2-only Review Engine Design

## Goal

删除 Review Context Engine v1 以及围绕 v1/v2 双轨产生的 Shadow、A/B、自动回滚和 UI 状态代码，使生产 Review、Skill Debug 和质量观测只存在一条 v2 执行链。完成改造后，用两个新的真实 MR 验证检视质量。

## Scope boundary

本次“v1”特指旧 Review Context Engine，不包括数据协议自身的版本号。以下标识继续保留：

- `finding_v1`、`review_input_v1` 等已落库数据契约。
- `skill_debug_validity_v1`、Skill 自身的 `version=v1`。
- PostgreSQL migration id、工具协议和 Prompt schema 的版本号。

这些标识不是可切换的旧检视实现，删除或全局改名会破坏历史数据兼容性。

## Architecture

### Single execution path

- `build_context` 无条件使用 Context Planner v2，不再读取或判断 `context_engine`。
- Context Health 仍输出 `context_engine=v2`，用于观测，不再作为运行开关。
- Production Review 与 Skill Debug 继续共用同一 Context Planner、Expert、Verify、Critic 和 Judge。
- Worker 不再识别 `quality_shadow_v1`、`quality_shadow_v2`，唯一有效业务作业是 `production_review` 或 Skill Debug 作业。

### Removed capabilities

- 删除 v1 Prompt 拼装分支。
- 删除冻结输入 Shadow 配对、v1 baseline 自动排队及 Shadow Pair 完成逻辑。
- 删除运行安全/质量门自动回滚到 v1 的 Worker 与 Common Backend 接口。
- 删除基于 v1/v2 Pair 的 uplift evaluator、脚本、fixture 和专项测试。
- 删除前端 `v1_rolled_back`、`rollback_pending` 和 Pair 数展示。

### Retained quality controls

- 保留 Context Health、Candidate Funnel、Judge 原因、Skill Checkpoint、复现指纹、反馈误报率和未闭环指标。
- 质量状态改为单引擎口径：`v2_unlabeled`、`v2_evaluating`、`v2_validated`。
- `v2_validated` 只表示已完成规定数量的人工/Gold 标注并达到绝对质量阈值，不再表示相对 v1 提升。
- 现有数据库中的 Shadow/rollback 历史表不主动 DROP，避免破坏历史审计；运行代码不再创建、写入或查询这些表，新的空库也不再创建它们。

## Configuration and compatibility

- 从示例配置、TypeScript/Python 配置类型和 README 删除 `context_engine`、`quality_shadow_mode`、`auto_shadow_baseline`、`auto_rollback_enabled`、`minimum_distinct_mrs` 和 v1 Gold A/B 路径。
- 已有部署配置里残留的旧字段按未知兼容字段忽略，不会重新启用旧能力。
- Review API 返回的 Context Health 固定为 v2；质量仪表盘不再显示回滚或 Pair 状态。

## Tests

先增加一个 v2-only 守卫测试，要求：

- `build_context.py` 不存在 v1 分支。
- Worker 不导入 Shadow/rollback 模块。
- package scripts 不再包含 Shadow/A/B/rollback verifier。
-配置类型不再接受 `context_engine: "v1"`。
- README 和前端不再宣称可回滚 v1。
- 协议版本白名单允许 `finding_v1` 等非引擎标识继续存在。

随后运行专项测试、全仓 `npm run verify` 和 `git diff --check`。

## Real-task validation

代码完成并重启 Worker 后，创建两个新的真实生产 Review；改造前已经开始的任务不计入结果。样本优先覆盖：

1. 一个实现/缺陷修复 MR，用于检查跨文件上下文和召回线索。
2. 一个依赖或配置类 MR，用于检查精确率和建议类误报抑制。

每个任务记录 MR、Head SHA、Run ID、文件数、Context Health、执行 Agent、LLM 调用、Candidate/最终 Finding、Judge 拒绝原因、Token、耗时和预算熔断。人工逐条核对最终 Finding 是否是可操作缺陷，并检查明显风险是否被漏掉。

## Acceptance criteria

- 代码中不存在 Review Context Engine v1 可执行路径。
- 不再生成 Shadow Job 或回滚请求。
- Production 与 Skill Debug 均固定走 v2。
- 全量验证通过。
- 两个改造后的真实 MR 均完成，且每条最终 Finding 都有明确证据和人工质量结论；发现的误报或漏报必须先修复并加入回归测试，不能仅记录后结束。
