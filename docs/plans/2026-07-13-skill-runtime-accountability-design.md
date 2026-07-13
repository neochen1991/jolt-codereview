# Skill Checkpoint 编译、Judge 决策审计与真实任务仪表盘设计

## 背景

当前 Skill 机制已经能够把结构化 Markdown 拆成 Checkpoint、按 Checkpoint 运行专家，并在项目页展示部分质量指标。但仍有三个结构性问题：

1. 上传校验由 TypeScript 解析 Markdown，Worker 运行时由 Python 再解析一次；两套实现可能产生不同 Checkpoint。
2. Judge 虽然会为多数拒绝候选填写 `rejected_reasons`，但缺少完整性约束、明确的人类可读原因以及输入输出守恒校验。
3. 当前指标从 Checkpoint coverage 和人工反馈中聚合，无法完整回答 Skill 是否应该被路由、是否实际加载、是否闭环。

本设计把 Skill 从文档到正式任务的链路收敛成三类不可变事实：编译产物、决策记录和运行事实。

## 目标

- 同一 Skill 版本在调试和正式任务中消费完全相同的 Checkpoint Manifest。
- Markdown 编译结果可解释、可定位、可验证，并且 ID 稳定。
- 进入 Judge 的每个 Skill Finding 都有最终去向；删除或合并必须有明确原因。
- 项目管理员能够在真实任务仪表盘看到路由、加载、执行、命中和人工反馈的完整漏斗。
- 调试任务继续复用正式执行链，但不进入正式任务指标，也不产生正式发布副作用。

## 非目标

- 本次不引入由 LLM 自由解释 Markdown 的非确定性编译器。
- 本次不把所有 Review 运行改造成通用事件溯源系统。
- 本次不改变 Skill 激活所需的调试证据门槛。

## 一、Markdown 到 Checkpoint Manifest

### 编译时机与唯一产物

Skill 上传或保存新版本时编译 Markdown。编译产物写入该不可变版本的 `checkpoint_manifest_json`，并记录 `checkpoint_compiler_version`。激活、Skill Debug 和正式任务只读取该 Manifest；Worker 不再对新版本重新解释 Markdown。

旧版本没有 Manifest 时允许使用现有 Python 解析器兼容运行，但运行事实必须标记 `legacy_fallback`，项目页显示升级提示。

### 支持的 Markdown 形式

编译器按确定性优先级识别：

1. `## SEC-CMD-001 标题` 或 `## Checkpoint: SEC-CMD-001 标题`。
2. Checkpoint 标题配合 `id` / `checkpoint_id` 字段。
3. “检查点”“Rules”“Checkpoints”等容器章节下的子标题。
4. 包含 ID、检查要求、证据要求等列的 Markdown 表格。

字段支持中英文别名，但最终统一成固定 Manifest Schema。代码块中的标题、字段和表格不得被解析。

### Manifest Schema

每个 Checkpoint 至少包含：

- `checkpoint_id`
- `title`
- `severity`
- `applies_to`
- `check`
- `required_evidence`
- `false_positive_patterns`
- `positive_examples`
- `negative_examples`
- `fix_guidance`
- `source_path`
- `source_heading`
- `source_line_start`
- `source_line_end`
- `parse_quality`

Manifest 顶层包含 Schema 版本、编译器版本、Skill key、源 bundle hash、编译时间、诊断信息和 Checkpoint 列表。

### 稳定 ID 与激活门禁

显式 ID 原样保留。未显式指定 ID 时，以 Skill key、源文件路径和规范化标题生成稳定 ID；正文修改不改变 ID。重复 ID、缺少检查要求、证据要求、误报排除或修复建议时，新版本不能激活，并返回文件、行号和诊断代码。

若自然 Markdown 无法可靠拆分，不再为新版本生成一个覆盖全文的模糊 Checkpoint。只有旧版本兼容路径可使用 `SKILL:<skill_key>` fallback。

## 二、Judge Finding 决策账本

### 状态模型

每个进入 Judge 的 Skill 候选必须最终处于以下状态之一：

- `retained`：保留为最终 Finding。
- `rejected`：明确拒绝。
- `merged`：与另一候选合并。

每条决策记录保存标准原因码、人类可读原因、决策阶段、决策时间、关键上下文、原始候选快照，以及合并目标 ID（如有）。

### 强制规则

- `rejected` 和 `merged` 不允许原因数组为空。
- 标准原因码通过集中注册表映射为中文原因模板。
- 未识别原因仍保存原始原因码，并生成可读兜底文本。
- Judge 结束时校验：`输入候选数 = retained + rejected + merged`。
- 守恒失败或缺少原因时不得无痕忽略；记录 `judge_unclassified_rejection` 和质量异常事件，并在运行与仪表盘中暴露。

现有 `candidate_findings` 继续作为候选账本，扩展 `decision_reason_json`、`decision_stage`、`decided_at` 和 `merged_into_candidate_id`。最终 `review_findings` 仍只保存对用户可见的 Finding。

## 三、真实任务 Skill 运行事实与仪表盘

### 事实模型

新增按运行、Skill、版本和 Agent 唯一的 Skill 运行事实，以及按 Checkpoint 实例唯一的 Checkpoint 事实。事实在正式运行中随生命周期更新，在 finalize 时校验并封口。

Skill 运行事实包含：

- 是否适用、适用原因和匹配文件
- 是否被 Router 路由
- 是否成功加载 Manifest
- Manifest 版本和 bundle hash
- 应执行、已完成、未闭环的 Checkpoint 数
- 原始命中、Judge 保留命中、Finding 数
- Judge 未分类删除数

Checkpoint 事实使用明确终态：`hit`、`clean`、`not_applicable`、`rejected`、`error`、`timeout`、`unresolved`。只有前四项属于已闭环；错误、超时和无终态属于未闭环。

### 指标口径

- 全量路由率 = 被路由正式任务数 / 全部正式任务数。
- 适用路由率 = 被路由正式任务数 / 根据 Manifest `applies_to` 判断应适用的正式任务数。
- 加载率 = 成功加载 Manifest 的任务数 / 被路由任务数。
- Checkpoint 完成率 = 有明确闭环终态的实例数 / 应执行实例数。
- 未闭环率 = error、timeout、unresolved 实例数 / 应执行实例数。
- 命中率 = 产生至少一个 Judge 保留 Finding 的实例数 / 已完成适用实例数。
- 误报率 = false_positive 或 dismissed 的 Skill Finding 数 / 有人工反馈的 Skill Finding 数。
- 人工反馈覆盖率 = 有人工反馈的 Skill Finding 数 / 可反馈 Skill Finding 数。

所有主指标只统计 `execution_kind = 'production_review'`。Skill Debug 可在单次运行详情中查看相同事实，但不进入仪表盘聚合。

### 页面

项目概览展示 KPI、分母、趋势和异常提醒；现有 Skill Checkpoint 质量区域升级为可下钻明细，支持按 Skill、版本、Checkpoint、Agent、模型和时间筛选。零分母显示“暂无数据”，不得显示为 0%。

## 权限与审计

仪表盘和 Judge 候选决策详情延续 `project_admin` 权限。普通项目成员只能看到最终 Review Finding，不暴露内部候选和 Judge 细节。

## 兼容与迁移

- 数据库迁移只增加列和事实表，不删除现有字段。
- 历史运行继续使用现有 coverage 聚合，标记为 `legacy_derived`；新运行使用结构化事实。
- 新 Skill 版本必须通过 Manifest 编译门禁；已激活旧版本不被强制停用。
- API 保留现有 `items` 和 `totals` 字段，并新增 funnel、denominators、health 和 version 维度。

## 验证策略

- 编译器夹具覆盖显式标题、字段式、自然章节、表格、代码块、重复 ID、稳定 ID和中英文别名。
- 合同测试证明上传校验产物、Skill Debug 和正式任务读取同一 Manifest。
- Judge 测试覆盖拒绝、合并、缺失原因和输入输出守恒。
- 指标测试覆盖所有分母、零分母、调试任务隔离和人工反馈覆盖率。
- 浏览器测试验证项目管理员能看到 KPI 和下钻原因，低权限用户无法访问。
