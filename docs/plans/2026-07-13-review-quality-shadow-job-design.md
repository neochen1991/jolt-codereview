# Review Quality Shadow Job 设计

## 背景与目标

质量优化方案要求在同一个冻结 MR 输入上执行 v1/v2，并以真实 Worker 结果计算 Recall、Precision、跨文件 Recall、Negative FP、Token 和耗时。现有 `run-review-quality-shadow.mjs` 只定义了通用 runner 协议，仓库内只有测试桩；直接把 `quality_shadow` 交给现有 Worker 又会被当成生产任务，存在更新 MR 状态或发布评论的风险。

本设计补齐原生 Shadow 作业能力，同时保持生产 Review 与 Shadow Review 使用同一张 Review 图、同一套专家、Judge、Skill Checkpoint 和 LLM Exchange 实现。

## 方案选择

采用原生 `quality_shadow_v1` / `quality_shadow_v2` 作业，不复用 Skill Debug 会话，也不让脚本绕过队列直接调用内部节点。

- 相比复用 Skill Debug，避免把单个 Skill 的 baseline/candidate 语义混入 Review Quality A/B。
- 相比脚本直调 Worker，保留队列、运行日志、Artifacts、重试和数据库审计链。
- 相比复制一套 Shadow Pipeline，共用生产 Review 图，防止评测流程与真实任务漂移。

## 数据流

1. 从已完成的生产 Review Run 导出冻结输入 Artifact，记录 MR、head SHA、Artifact SHA256 和 Gold 标注引用。
2. Shadow Runner 校验输入哈希，为同一 Snapshot 各创建一个 `quality_shadow_v1` 和 `quality_shadow_v2` 作业。
3. Worker 以最低队列优先级领取作业，从冻结 Artifact 恢复 changed files、文件内容和增量上下文，不重新读取变化中的远端 MR。
4. Worker 只覆盖 `context_engine`，其余项目配置、Skill 绑定、模型和数据策略保持一致，并运行正式 Review 图。
5. Finding、Trace、LLM Exchange 和 Review Artifacts 仍按各自 run ID 落库；评论发布、MR 状态更新、反馈学习和生产历史写入全部禁用。
6. Runner 等待两个作业结束，校验输入 SHA、发布尝试数和终态，再输出统一 case result；聚合脚本生成质量门报告。

实现采用 `review_input_snapshots`：项目显式开启 `quality_shadow_mode` 时，production run 捕获 Worker 实际使用的 changed files、源文件内容和增量历史，规范化哈希后保留 72 小时。原生 case runner 通过 Snapshot ID 和 SHA256 引用该输入，不在 JSONL 中重复保存源码全文。

## 隔离与失败处理

- `quality_shadow_*` 与 `skill_debug_*` 统一归类为 non-production review job；`production_side_effects_allowed()` 对两者都返回 false。
- 生产任务始终优先；同一项目存在生产排队时不领取 Shadow，且 Shadow 使用独立并发上限。
- Shadow 失败只更新自身 job/run，不修改 `merge_requests.review_status`。
- Snapshot 缺失、哈希不一致、head SHA 不一致、v1/v2 输入 SHA 不一致或出现发布尝试时，case 直接失败且不得计入有效样本。
- 30 个真实 MR 和双人 Gold 标注是上线证据，不由机制测试或重复 fixture 代替。

## 验证

- 单元测试：作业分类、生产副作用隔离、配置覆盖、冻结输入读取与哈希校验。
- 队列测试：生产优先、Shadow 并发限制、失败不修改 MR 状态。
- 集成测试：同一 Snapshot 生成 v1/v2 两个真实作业，均经过正式 Review 图并产出独立 run/artifacts，发布尝试为 0。
- 质量门测试：少于 30 个有效 MR、缺少 Gold 指标或成本指标时必须失败。

## 切换边界

该能力只让真实 Shadow A/B 可执行、可审计，不自动把默认 `context_engine` 切到 v2。默认切换仍受已批准方案中的分阶段 30 MR 质量门约束。
