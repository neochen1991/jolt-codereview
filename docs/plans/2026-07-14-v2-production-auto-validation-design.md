# v2 生产切换与自动验证设计

## 决策

生产 Review 默认立即切换到 Context Engine v2，同时启用真实输入冻结和 v1 背景 Shadow。用户已确认：当运行安全指标或具备双人 Gold 的质量指标不达标时，系统自动回滚到 v1。

“已切换”和“已证明提升”是两个独立状态：切换后立即显示 `v2_provisional`；只有至少 30 个不同真实 MR、同输入 v1/v2 对照、双人 Gold 复核和全部质量门通过后，才显示 `v2_verified`。缺少样本或 Gold 时不得显示提升结论，也不得用 fixture、重复 MR 或模型自标注代替。

## 方案选择

采用“v2 主任务 + v1 自动 Shadow + 双层回滚门”。

- 不采用“只改默认配置”：无法证明真实任务效果，也没有回退保护。
- 不采用“先灰度再切换”：与本次直接切换决定不一致。
- 不为 Shadow 复制 Review Pipeline：v1 对照继续使用正式 Worker 图，只通过 execution kind 覆盖 Context Engine 并禁止生产副作用。

## 执行链

1. 新生产任务使用 v2，并强制捕获 72 小时冻结输入 Snapshot。
2. v2 run 成功结束后，按 `project + MR + head + snapshot hash` 幂等创建一个 `quality_shadow_v1` 作业。
3. v1 Shadow 使用同一 Snapshot、项目配置、模型、Agent、Skill、Checkpoint、Verify、Critic 和 Judge；只覆盖 Context Engine。
4. `review_quality_shadow_pairs` 记录 v2 production run、v1 shadow run、输入 hash、终态、Token、耗时和 Finding 数，供仪表盘与评测使用。
5. 两名评审人员仍通过版本化 Gold JSONL 独立标注；每条最终 Gold 必须带 reviewer、复核状态和分歧解决原因。Worker 只读取显式配置的 Gold 文件，不生成 Gold。
6. 每个 pair 完成后重新计算当前阶段的 v1/v2 Precision、Recall、跨文件 Recall、Critical/High Recall、Negative FP、P95 Token 和 P95 Duration。

## 自动回滚

### 运行安全门

无需 Gold 即可执行：最近 10 个不同 MR 中出现 3 个连续 v2 失败，或失败/blocked 比例超过 20%，立即请求 Common Backend 把项目 `review_quality.context_engine` 改回 v1，并写审计日志。

### 质量门

只有以下证据齐全时执行：至少 30 个不同真实 MR、每个 MR 有同输入 v1/v2 pair、Gold 完成双人复核、成本和耗时数据完整。门槛沿用 Review Quality v2 方案：

- Recall 提升至少 10pp。
- 跨文件 Recall 提升至少 15pp。
- Critical/High Recall 至少 95%。
- Precision 相对 v1 回退不超过 2pp。
- Negative FP 不高于 v1。
- P95 Token 和 P95 Duration 不超过 v1 的 1.5 倍。

任一门失败自动回滚 v1；证据不足保持 `v2_provisional`，不触发质量结论。

## 配置与权限

`review_quality` 增加：

```json
{
  "context_engine": "v2",
  "quality_shadow_mode": true,
  "auto_shadow_baseline": true,
  "auto_rollback_enabled": true,
  "minimum_distinct_mrs": 30,
  "gold_dataset_path": "evaluation/production_review_quality_gold.jsonl"
}
```

Common Backend 新增仅内部服务 Token 可调用的回滚接口。Worker 不能直接修改 Common 所有的 `project_settings`；接口只允许把 `context_engine` 从 v2 改为 v1，必须记录触发门、指标、样本数、来源 run 和时间。

## 失败处理

- Snapshot 创建失败：生产 v2 结果保留，但状态标记 `validation_input_missing`，不创建 Shadow，不计入质量样本。
- v1 Shadow 失败：生产结果不受影响，pair 标记失败并进入运行安全统计。
- Common 回滚接口不可用：写入 `rollback_pending` 和错误日志，每次新 pair 完成后重试；不得谎报已回滚。
- Gold 路径缺失、格式错误或复核不完整：状态为 `gold_unavailable` / `gold_invalid`，不计算提升。

## 验证

- TDD 覆盖默认 v2、自动 Snapshot、幂等 v1 Shadow、生产优先、副作用隔离和 pair 完成。
- 使用当前数据库中的真实 MR 重新运行一次 v2，验证真实 Worker run 的 `coverage_json.context_engine=v2`、Snapshot 和 v1 Shadow pair。
- 全仓 `npm run verify` 必须通过。
- 单个真实 MR 只证明链路可运行；质量提升结论仍必须等待 30 个不同 MR 和双人 Gold。
