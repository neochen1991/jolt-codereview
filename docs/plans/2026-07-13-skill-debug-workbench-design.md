# Skill 调试工作台设计

## 目标

让 Skill 调试人员能够在已绑定的专家 Agent 上选择真实 MR，执行一次可追踪的 Skill 调试任务，并看到 Skill 加载、路由、Prompt、LLM、工具、checkpoint 和 Finding 全链路证据。

## 核心约束

调试不是独立模拟器。`skill_debug` 与正式 Review 使用同一 Review Service、Worker 图、配置解析、Skill Loader、Prompt Builder、模型、工具、checkpoint 解析、Finding 质量门禁和持久化逻辑。调试模式只限制目标 Agent/Skill、提高日志可见性并禁止发布，不复制执行实现。

系统支持两种调试模式：

- `targeted`：强制执行 Skill 所绑定的目标 Agent，用于确认 Skill 自身效果。
- `production_route`：完全使用正式路由，用于确认真实任务是否会选择目标 Agent 和 Skill。

页面必须区分两种模式，不能把定向执行成功描述为生产路由必然执行。

## 运行流程

1. 用户从专家 Agent 的 Skill 绑定项点击“调试 Skill”。
2. 用户选择当前项目的真实 MR 和运行模式。
3. 后端校验 Skill 绑定、Agent、MR 和项目归属，创建带不可变调试上下文的 Review Job。
4. Worker 仍从正式队列消费该 Job，并从 Job 调试上下文读取目标 Skill、目标 Agent和模式。
5. 正式 Worker 图执行；`targeted` 模式只在路由输出处把目标 Agent 纳入最终选择，其他节点不分叉。
6. 调试任务禁止进入发布动作，产出的 Findings、trace、LLM和工具记录继续使用正式表结构。
7. 调试工作台从统一详情接口读取运行快照和现有 trace 数据。

## 工作台

工作台提供概览、加载与绑定、路由、Prompt、LLM、工具调用、Checkpoints、Findings 和原始日志九类视图。第一期以一个页面内分区呈现，保留后续拆分标签页的稳定数据契约。

顶部结论必须直接回答：

- Skill 是否加载成功。
- 目标 Agent 是否执行；如未执行，为什么。
- checkpoint 执行、命中、过滤和未执行数量。
- 产生多少 Finding。
- 本次是定向执行还是严格生产路由。
- 运行快照是否具备生产一致性证据。

## 一致性证据

每个调试任务保存以下快照字段：目标 Skill、目标 Agent、运行模式、Skill 版本、MR head SHA、项目 ID、创建时有效配置摘要。Worker 在已有 `coverage_json`、trace、LLM 和工具记录中继续写入实际加载资源、Prompt/模型和执行证据。

一致性状态不是简单布尔承诺，而是逐项证据：同一 MR SHA、同一项目配置解析入口、同一 Skill Loader、同一 Prompt Builder、同一模型策略、同一工具注册表和同一质量门禁。缺少证据时显示“待验证”，不得显示“通过”。

## 安全和错误处理

- 调试任务永远不可发布 MR 评论。
- 只有具备项目 reviewer 权限的用户可创建和查看。
- Skill 或绑定不存在、绑定停用、MR 不属于项目时返回明确错误。
- 完整 Prompt 和 LLM 数据沿用项目访问控制；日志页面明确标注可能含代码和敏感上下文。
- Worker 失败时仍保留已经写入的 trace，并显示最后成功阶段与错误信息。

## 测试

- API 契约测试验证创建参数、权限、绑定校验和返回结构。
- Worker 契约测试验证调试上下文进入同一执行图、定向模式只影响路由选择、调试任务不可发布。
- 前端静态契约与构建验证调试入口、MR 选择、模式提示和九类证据区。
- 一致性测试比较正式模式和 `production_route` 调试模式的 Agent、Skill、Prompt、工具、checkpoint 与 Finding 契约，排除 ID 和时间戳。

