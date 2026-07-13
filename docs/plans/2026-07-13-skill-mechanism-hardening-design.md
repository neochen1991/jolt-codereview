# Skill 机制可靠性加固设计

## 背景与目标

当前 Skill Debug 已经复用正式 Review Worker Graph，并隔离了 MR 状态、Finding 历史和发布副作用。但现有实现仍存在版本资产双写、无效运行被标记完成、发布可绕过调试、指标归因过宽、快照不完整、调试占用正式队列、权限过粗以及脚本能力契约含糊等问题。

本次加固的目标是：让正式任务与调试任务解析同一个不可变 Skill 版本；让“调试完成”只表示具备有效证据的执行；让版本发布经过服务端强制门禁；让对比指标可归因到目标 Agent、Skill 和 checkpoint；让 A/B 使用相同输入工件；让调试资源不阻塞正式任务；让 Skill 开发者不必获得项目管理员权限；明确上传脚本只读、不可执行的安全契约。

## 方案选择

### 方案 A：继续维护 active 投影并修补同步

保留 `custom_skills`、`custom_skill_assets` 和 `custom_skill_versions.assets_json` 三份状态，在每次上传、激活和迁移时同步。改动较小，但事务边界复杂，仍然可能产生调试和生产读取不同内容的问题。

### 方案 B：不可变版本为唯一事实源，active 只保存指针

所有 Skill 正文和资产写入不可变版本；项目级 Skill 记录只指向当前 active version。正式 Worker、调试快照、版本详情和发布门禁都通过同一个版本解析器读取。现有 active 投影仅作为迁移兼容输入，不再作为运行时事实源。

### 方案 C：每个 Skill Bundle 外置为文件/对象存储工件

数据库只保存内容地址和元数据。长期扩展性最好，但会引入新的对象存储、签名、清理和部署依赖，超出本次范围。

采用方案 B。它能在不增加外部基础设施的前提下，消除最关键的一致性风险，并为后续对象存储留出内容寻址接口。

## 一、不可变 Skill 版本

`custom_skill_versions` 成为运行时唯一事实源，每个版本保存：

- 正文和完整资产清单；
- `bundle_sha256`；
- 生命周期状态；
- 校验报告；
- 创建人和时间。

`custom_skills` 保存 Skill 身份和 `active_version_id`。生产 Worker 不再分别查询 active 正文和实时资产，而是先解析 active version，再一次性读取同一个 Bundle。调试快照使用完全相同的解析服务。

兼容迁移会为历史 `custom_skills + custom_skill_assets` 合成缺失版本，并校正已有 active 版本缺少资产的情况。迁移必须幂等，不能覆盖已经完整且哈希一致的不可变版本。

所有新版本只能创建为 `draft`。资产上传仅允许修改 draft。激活只改变 active 指针和版本状态，不复制正文或资产。

## 二、发布门禁

服务端始终执行 Bundle 结构校验，客户端不能通过参数关闭。版本激活必须满足：

1. Bundle 校验通过；
2. 存在同一 `bundle_sha256`、同一 Agent 的有效 targeted 调试；
3. 存在同一 `bundle_sha256` 的有效 production-route 调试；
4. 两次调试都没有 stale、degraded、inconclusive、failed、cancelled 或 timed-out 状态。

系统管理员可使用显式 break-glass 参数跳过调试门禁，但必须填写原因并记录审计；项目管理员不能跳过。

## 三、有效性状态

Skill Debug 会话状态扩展为：

- `queued`、`running`；
- `completed`：满足有效性契约；
- `inconclusive`：流程结束但证据不足；
- `degraded`：输入、模型或关键工具降级；
- `failed`、`cancelled`、`timed_out`、`stale_head`、`expired`。

有效性契约至少要求：

- MR diff 成功获取且存在可检视文件；
- 目标 Agent 实际启动；
- candidate 中目标 Skill 的目标版本和哈希实际加载；
- 所有结构化 checkpoint 都有 checked、skipped 或 rejected 结果；
- 至少一次目标 Agent 的成功 LLM 调用，或者 Skill 明确声明为 static-only 且存在成功静态工具证据。

页面必须优先展示无效原因，不能把 `no_issue` 等同于 Skill 有效。

## 四、目标级归因

Trace、LLM 调用、工具调用和 Finding 的诊断统一按以下维度归属：

- `agent_id`
- `skill_key`
- `skill_version`
- `bundle_sha256`
- `checkpoint_id`
- `debug_variant`

诊断服务只统计目标范围的数据。Finding 对比使用稳定的语义指纹，并区分 added、removed、unchanged 和 changed。`skill_loaded` 只表示注入成功；另行提供 `skill_evidence_complete` 表示 checkpoint 与调用证据完整。

## 五、可复现 A/B 输入

会话创建时生成内容寻址的执行输入工件，包括：

- MR changed files、patch 和允许读取的源码内容摘要；
- 路由输入和生产路由结果；
- 静态工具清单、版本与可复用输出；
- 完整有效配置快照；
- Worker build SHA、Prompt contract version；
- 模型 provider、model、temperature、seed 和缓存策略。

targeted 的 baseline/candidate 共享同一个输入工件，不重复拉取 VCS。为避免固定顺序偏差，会话记录执行顺序；默认在可用并发下并行，否则按 session ID 稳定交替先后顺序。比较报告必须展示缓存命中和不可控差异。

“重跑同一输入”和“在最新 MR 上重新验证”拆分为两个操作：前者复用完整快照，后者创建新输入工件和新哈希。

## 六、调试资源隔离

保留统一 Review Graph，但队列调度区分 `production_review` 与 `skill_debug_*`：

- 正式任务拥有保留并发和更高调度优先级；
- 调试任务使用独立并发上限；
- targeted 会话按实际 Job 数占用配额；
- 当正式任务排队时，不再领取新的调试 Job；
- Token、调用和时长预算继续按用户与项目限制。

本次不复制 Worker 代码；通过同一 Worker 中的队列类别和并发计数实现资源隔离。

## 七、`skill_developer` 权限

角色等级中增加 `skill_developer`，权限采用能力检查而不是简单等级继承：

- 可查看 Skill、创建 draft、上传 draft 资产、绑定到允许的 Agent；
- 可创建、查看、取消和导出自己发起的调试；
- 可查看经过脱敏且仅属于自己会话的高级日志；
- 不可激活版本、修改项目模型/密钥/队列/发布配置；
- 不可查看其他人的调试 Prompt 或源码上下文；
- project_admin、system_admin 和 root 保留全项目管理能力。

## 八、脚本能力契约

本期明确采用“只读脚本资源”策略：

- `scripts/` 可以作为规则实现示例和参考资料上传；
- `executable` 不代表平台会执行，只表示资产作者声明其语义类型；
- `run_skill_script` 始终返回 `blocked_by_policy`，并在 UI 和校验报告中明确说明；
- 校验器对脚本执行指令给出警告，禁止宣称脚本已运行；
- Skill 有效性不能依赖脚本执行结果。

未来若支持脚本，必须单独建设无默认网络、无项目凭据、只读源码、受限 CPU/内存/时间和命令白名单的沙箱，本次不实现伪沙箱。

## 数据迁移与兼容

迁移步骤：

1. 增加版本哈希、校验报告、active version 指针和调试有效性字段；
2. 从历史 active 投影合成或修复不可变版本；
3. 将生产读取切换到统一版本解析器；
4. 保留旧表字段供回滚读取，但停止运行时写入；
5. 通过一致性检查确认 active 指针、版本哈希和资产数量匹配。

旧调试会话没有完整输入工件时标记为 legacy，不允许作为新发布门禁证据。

## 测试与验收

自动化测试至少覆盖：

- active 历史数据迁移后，正式和调试解析得到相同 Bundle/hash；
- 新版本不能直接 active，服务端强制校验；
- 没有 targeted 和 production-route 有效证据时不能激活；
- 空 diff、VCS 降级、零成功 LLM 调用得到 inconclusive/degraded；
- 指标只统计目标 Agent/Skill/checkpoint；
- baseline/candidate 使用相同输入工件；
- 正式任务排队时调试任务不占用保留并发；
- skill_developer 只能管理 draft 和自己的调试；
- scripts 明确不可执行且不能形成成功证据；
- 正式 Review、发布隔离、取消、超时和过期回归测试通过。

浏览器验收覆盖项目管理员完整发布流程、skill_developer 草稿与调试流程、普通 reviewer 无入口，以及 degraded/inconclusive 的可理解提示。
