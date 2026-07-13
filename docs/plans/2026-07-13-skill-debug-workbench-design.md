# Skill 调试工作台完整隔离设计

## 目标

Skill 调试必须同时满足两个看似冲突、实际可以兼容的条件：

1. Prompt、模型、工具、路由、质量门禁和执行顺序与正式 MR 检视使用同一套生产实现。
2. 调试任务不得覆盖正式任务，也不得修改 MR 正式状态、问题历史、反馈学习或发布结果。

实现采用“独立调试会话 + 同一 Review Worker Graph + 隔离副作用”的架构，不建设第二套 Debug Worker。

## 核心对象

新增 `skill_debug_sessions`，每次调试创建独立会话。会话保存：

- 项目、仓库、MR 和固定 head SHA；
- Skill、Agent、调试模式和操作者；
- 草稿或已激活 Skill 的不可变内容快照、资源快照和 SHA256；
- Agent、规则、工具、模型、预算及数据策略快照；
- baseline/candidate 对应的 job 和 run；
- 状态、取消信息、超时、Token、耗时、保留期限和审计信息。

`review_jobs` 增加执行分类和调试会话关联：

- `production_review`：正式检视；
- `skill_debug_baseline`：不加载目标 Skill 的对照执行；
- `skill_debug_candidate`：加载目标 Skill 的候选执行。

正式 job 保留 MR + SHA 幂等语义；每个 Debug job 拥有独立 ID，不与正式 job 或其他 Debug job冲突。每次会话和 run 都能被稳定寻址，轮询不能退回旧 run。

## 执行一致性

三类 job 都进入同一个生产执行图：

```text
fetch_mr -> choose_effort -> prescan -> build_context -> route_agents
-> run_experts -> verify_findings -> detect_conflicts
-> run_targeted_debate -> judge_findings -> summarize_pr -> finalize
```

不得复制 Skill Loader、Prompt Builder、Tool Gateway、模型调用或 Finding 质量门禁。差异只通过显式的 execution context 注入：

- 正式任务使用当前有效项目配置；
- 调试任务使用创建会话时冻结的配置快照；
- Worker 节点仍执行同一实现；
- finalize 和各阶段状态写入通过统一副作用策略决定是否更新 MR 正式数据。

## 调试模式与效果归因

### 严格生产路由

不修改正式路由结果。若目标 Agent 未被选择，页面明确显示“目标 Skill 未实际执行”及路由原因。该模式回答“真实生产任务是否会触发这个 Skill”。

### Skill 定向调试

创建一对可比较执行：

- baseline：强制加入目标 Agent，但从冻结绑定快照中移除目标 Skill；
- candidate：同样强制加入目标 Agent，并加载目标 Skill；
- 两次执行使用相同 MR SHA、Agent、规则、工具、模型参数、预算和数据策略。

该模式回答“加入这个 Skill 后发生了什么变化”。页面按 `skill_key`、checkpoint 和 Finding 来源展示新增、消失、保持不变的结果，以及 Token、耗时和调用差异。

## 草稿、审核与激活

Skill 生命周期支持：

```text
draft -> debugging -> reviewed -> active -> archived
```

项目管理员可以调试草稿版本，而不需要先启用生产绑定。正式任务只读取 `active` 版本。调试创建时把 Skill 正文和 assets 冻结到会话快照；排队后修改或删除 Skill 不改变已经创建的会话。

激活操作展示最近一次候选调试的结果摘要和版本哈希，但本期不强制把“调试成功”作为激活硬门禁，避免无合适 MR 时阻断管理操作。

## 副作用隔离

调试 job 可以更新自身 job/run/session 状态，但禁止：

- 修改 `merge_requests.review_status`；
- 更新 `mr_finding_history` 或把正式问题标记为 resolved；
- 写入反馈学习、规则精度和正式质量统计；
- 成为 MR 默认最新正式结果；
- 发布 GitHub/CodeHub 评论；
- 被正式 Findings、Review Summary 和增量上下文查询默认读取。

发布接口必须沿 finding -> run -> job 检查 `execution_kind`。任何来自 Debug job 的 finding 都返回 409，不能依赖 MR 的“最新 job”判断。

## MR 与配置快照一致性

会话创建时保存 MR head SHA。Worker 拉取后必须校验实际 head SHA；如果 MR 已更新，则会话终止为 `stale_head`，不自动换用新代码。

冻结快照至少包含：

- Skill 正文、assets、版本和内容哈希；
- Agent 画像、自定义 Prompt 和启用状态；
- Skill、规则、工具绑定；
- 模型 provider、base URL 标识、model、temperature、seed 和预算；
- 数据策略、工具策略和路由策略；
- 生产执行契约版本。

密钥不得进入快照。快照只保存环境变量名或凭据引用。

## 权限和审计

创建、查看、取消、重跑、比较和导出调试会话统一要求项目管理员、系统管理员或 root。前端入口和后端 API 使用同一角色门槛。

审计事件覆盖：

- 创建、取消、重跑、查看详情、导出；
- 草稿版本选择和激活；
- 配额拒绝、超时、MR SHA 失效；
- Debug finding 发布拦截。

普通 reviewer/developer 即使知道 API 地址，也不能读取 Prompt、工具参数、源码片段或调试结果。

## 配额、取消和超时

项目配置提供调试治理参数：

- 项目并发上限和单用户并发上限；
- 每日会话次数和 Token 上限；
- 单次最大 LLM/工具调用及最长运行时间；
- baseline/candidate 是否允许并行执行；
- 调试记录和文件日志保留天数。

取消操作设置会话和关联 job 的取消状态。Worker 在节点边界检查取消/超时，已写入的 Trace 保留，未执行步骤显示原因。

## 日志安全与诊断包

页面默认显示结构化诊断，不直接铺开完整原始 JSON。诊断结论包括：

- Skill 是否加载及实际版本/哈希；
- Agent 是否被生产路由或定向路由选择；
- checkpoint 的执行、命中、跳过和失败原因；
- LLM、工具成功率和降级原因；
- baseline/candidate Finding、Token 和耗时差异；
- MR SHA、配置快照和生产执行契约证据。

高级日志继续提供 Trace、LLM 和工具记录。所有字段经过统一递归脱敏；Prompt 默认只持久化哈希，允许项目策略显式开启受限的短期明文保留。诊断包导出为脱敏 JSON，记录审计事件，并受相同管理员权限保护。

## API

核心接口：

- `POST /api/mr-review/projects/:projectId/skill-debug-sessions`
- `GET /api/mr-review/projects/:projectId/skill-debug-sessions`
- `GET /api/mr-review/skill-debug-sessions/:sessionId`
- `POST /api/mr-review/skill-debug-sessions/:sessionId/cancel`
- `POST /api/mr-review/skill-debug-sessions/:sessionId/rerun`
- `GET /api/mr-review/skill-debug-sessions/:sessionId/export`

创建接口接受 MR、Skill 版本、Agent、模式和 effort。服务端负责解析绑定、冻结快照和创建 job，不能接受客户端上传的任意执行配置。

## 前端工作台

工作台包含：

- 创建区：真实 MR、草稿/正式版本、Agent、调试模式和预估资源；
- 当前诊断：状态、加载、路由、checkpoint、LLM、工具和 Findings；
- A/B 对比：新增、消失、相同 Finding，以及 Token/耗时差异；
- 历史：按 Skill、版本、MR、模式、操作者和状态筛选；
- 操作：取消、重跑、两次会话比较、复制链接和导出诊断包；
- 高级日志：按阶段过滤的 Trace、LLM 和工具记录。

路由和一致性证据缺失时显示“未执行”或“待验证”，不得显示成功。

## 迁移与兼容

现有带 `debug_context_json` 的 job 视为 legacy debug。迁移保留历史数据但不再创建这种 job；详情接口可以只读兼容。正式任务查询统一增加 `execution_kind = 'production_review'`，避免旧 Debug run 被误认为最新正式结果。

## 测试与验收

自动化测试至少覆盖：

- reviewer/developer 调用所有调试 API 返回 403；
- 同 MR、同 SHA 的调试不覆盖正式 job；
- 连续调试产生独立 session、job 和 run；
- 调试不修改 MR 状态和 finding history；
- Debug finding 永远不能发布；
- 草稿可调试但正式任务不可加载；
- 排队后修改 Skill 不影响冻结快照；
- 轮询严格绑定本次 session/run；
- baseline/candidate 进入同一 Worker Graph；
- 严格生产路由不干预 Agent 选择；
- MR head 变化产生 `stale_head`；
- 配额、取消、超时和日志脱敏生效；
- 正式 Review 回归测试保持通过。

最后使用真实浏览器完成项目管理员创建草稿 Skill、选择 MR、定向 A/B 调试、查看历史和导出的端到端验证，并用普通 reviewer 验证入口不可见和 API 被拒绝。
