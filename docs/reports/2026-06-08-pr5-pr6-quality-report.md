# PR5 / PR6 真实检视质量评估报告

评估时间：2026-06-08 21:44 北京时间

评估对象：

- PR5: `neochen1991/jolt-benchmark#5`，`[codex] add dynamic risk policy benchmark issues`
- PR6: `neochen1991/jolt-benchmark#6`，`[codex] add archive import benchmark issues`

评估口径：

- 只按最终页面可见的 `review_findings` 计分，不按候选 finding 或日志中的中间观察计分。
- 召回率按预埋清单 20 个问题逐条匹配。
- 假阳率按最终 finding 中无法映射到预埋问题、或源码证据明显不成立的问题计算。
- 一个 finding 可以覆盖多个高度相关的预埋问题；重复命中同一预埋问题不增加召回。

## 总览

| PR | 最终问题数 | 严格命中预埋问题 | 严格召回率 | 可接受弱命中 | 宽松召回率 | 误报/偏题数 | 假阳率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| PR5 | 21 | 8/20 | 40.0% | 1 | 45.0% | 10 | 47.6% |
| PR6 | 14 | 9/20 | 45.0% | 1 | 50.0% | 4 | 28.6% |
| 合计 | 35 | 17/40 | 42.5% | 2 | 47.5% | 14 | 40.0% |

结论：当前工具已经能完整跑通 GitHub PR 拉取、真实静态工具、tree-sitter 代码图谱、多 Agent、DeepAgents skill、Judge 合并和最终问题入库。但检视质量距离“有效问题检出率 90% 以上、假阳率不超过 10%”差距仍然很大。本轮主要问题不是流程未跑通，而是专家输出和 Judge 合并阶段丢失了很多已在上下文中可识别的问题，同时存在源码位置和描述不一致的误报。

## PR5 质量评估

PR5 run id: `run_b7096df764c84085`

最终状态：`waiting_confirmation`

最终 finding 数：21

严格命中：

- #1 硬编码管理密钥：命中，`源码中硬编码管理密钥`。
- #2 管理密钥通过请求参数传递：命中，`管理密钥通过查询参数传输`。
- #5 外部可控 `pluginClassName` 进入 `Class.forName()`：命中，`外部可控类名进入反射加载`。
- #7 静态 `HashMap` 非线程安全：命中，`共享非线程安全对象` / `风险策略写入静态 HashMap`。
- #11 `evaluate()` 未校验 merchantId 与订单归属：命中，`订单读取未在数据库查询条件中限定 merchantId` / `支付风控评估接口缺少资源归属和权限校验`。
- #12 `previewForMerchant()` 调用 `findAll()` 并暴露全局订单摘要：弱命中，最终 finding 识别了 `preview` 使用 `findAll()`，但主要按性能问题描述，未明确指出跨商户数据泄露。
- #15 固定种子 `SecureRandom`：命中，`SecureRandom 使用固定种子`。
- #20 策略保存和评估接口缺少真实认证授权：命中，`风险策略管理接口缺少服务端认证授权` 和评估接口权限问题。

未命中：

- #3 用户提交表达式通过 `SpelExpressionParser` 执行。
- #4 `StandardEvaluationContext` 暴露完整 `PaymentOrder` 根对象。
- #6 插件加载失败默认返回 `order -> false`，导致失败默认放行。
- #8 策略缓存固定 key `"active"`，跨商户覆盖。
- #9 `lastPolicy` 静态全局变量造成跨商户状态污染。
- #10 `paymentId` 查不到时 fallback 到 `payments.findAll().stream().findFirst()`。
- #13 `previewForMerchant()` 返回 `POLICY_CACHE.get("active")` 暴露其他商户策略。
- #14 `Random` 用于风控采样桶。
- #16 `BigDecimal.equals(new BigDecimal("1000.0"))` scale 误判。
- #17 默认 SpEL 表达式构造 `new BigDecimal(...)` 扩大执行能力。
- #18 `lastPolicyAgeSeconds` 直接访问 `lastPolicy.getUpdatedAt()` 可能 NPE。
- #19 `priority` 字段保存但未参与策略选择。

PR5 典型误报：

- `BigDecimal 使用 double 计算结果构造`：最终 finding 描述 `doubleValue() * RANDOM.nextDouble()`，但真实源码是 `new BigDecimal("1000.0")` 和 `equals` 比较，描述与源码不符。
- `策略不存在时直接解引用 policy`：真实源码使用 `getOrDefault(...)`，`policy` 不会为空；真正风险是 `lastPolicy.getUpdatedAt()` NPE。
- `读取候选订单首元素前未处理空集合`：真实 `previewForMerchant()` 使用 `all.isEmpty() ? "" : all.get(0)`，描述与源码不符。
- `Map 返回类型不应返回 null`：真实源码没有 `return null`。
- `聚合归属或状态被外部任意改写`：当前文件没有 setter 或 reassign 方法，证据不足。

## PR6 质量评估

PR6 run id: `run_02a9455e91a94a8a`

最终状态：`waiting_confirmation`

最终 finding 数：14

严格命中：

- #1 `ObjectInputStream.readObject()` 不安全反序列化：命中。
- #3 `ZipEntry.getName()` 拼接目标路径，Zip Slip：命中。
- #4 解压目标目录由请求参数控制：命中。
- #5 ZIP 无大小、数量、压缩比限制：命中。
- #9 用户可控正则导致 ReDoS：命中。
- #10 `payments.findAll()` 后内存过滤：命中。
- #15 `outputDir` + 文件名任意路径写入：命中。
- #19 `corrections` 缺少 null/范围/数量校验：弱命中，仅识别了 null 风险，没有覆盖范围和数量。
- #20 导入/导出接口缺少认证、授权和商户归属校验：命中。

未命中：

- #2 `ArchiveImportCommand` 可序列化命令对象缺少反序列化白名单、版本控制或完整字段校验。
- #6 ZIP 解压未校验符号链接或特殊文件。
- #7 `mkdirs()` 返回值未检查。
- #8 `ZipInputStream` 未 try-with-resources 关闭。
- #11 CSV 字段未转义逗号、换行和引号。
- #12 CSV 公式注入。
- #13 `Content-Disposition` 文件名未净化，可能响应头注入。
- #14 `fileName` 未真正限制路径分隔符、控制字符和长度。
- #16 `getBytes()` / `writeString()` 未指定字符集。
- #17 `LocalDateTime.now()` 无时区和审计时钟。
- #18 可预测临时文件名。

PR6 典型误报或偏题：

- `ObjectInputStream 未使用 try-with-resources 关闭`：这是有效资源问题，但不在预埋清单；预埋的资源问题是 `ZipInputStream` 未关闭。
- `importSerializedCommand 缺少畸形输入回归测试`：测试覆盖建议，不是预埋代码缺陷。
- `SettlementArchiveService 暴露 Web 传输对象，应用服务边界被污染`：偏 DDD 设计建议，不是本轮预埋问题。
- `归档导入命令缺少值对象表达关键业务概念`：只能弱关联字段校验，不能等价于反序列化白名单或版本控制问题。

## 工具链表现

两个 PR 都真实执行了开源静态工具链和 tree-sitter：

- PR5 tree-sitter: 29 个文件、29 个类、103 个函数、257 个调用、87 个影响符号。
- PR6 tree-sitter: 15 个文件、15 个类、43 个函数、253 个调用、44 个影响符号。
- PR5 静态工具候选观察数：4，主要来自 Semgrep，包括静态可变集合、SpEL、反射等。
- PR6 静态工具候选观察数：1，主要是 `ObjectInputStream.readObject()`。
- PMD、Checkstyle、Gitleaks 均真实运行；SpotBugs 因无编译产物跳过；依赖和 IaC 工具因无对应目标跳过。

工具链问题：

- Semgrep 已经在 PR5 给出 SpEL 和 unsafe reflection 候选，但最终只保留了反射，SpEL 没进入 final finding。
- DeepAgents 低级缺陷阶段已在工具摘要中识别出 PR5 的 NPE、BigDecimal、异常吞掉等候选，但最终 LLM 输出只保留静态 HashMap 并发问题，导致召回下降。
- Judge 会把部分测试 finding、异常吞掉等作为重复或辅助问题过滤掉；当前过滤策略对 benchmark recall 过于激进。
- 部分 LLM finding 出现源码幻觉，说明最终 verifier 没有强制用真实行内容校验问题描述。

## 改进建议

1. 最终 finding 必须做源码锚点一致性校验：标题、描述、证据中的代码片段必须能在 `file_path:line_start-line_end` 找到，否则直接降级或丢弃。
2. 对静态工具高置信候选建立“必须裁决”机制：Semgrep 命中 SpEL、反射、Zip Slip、反序列化时，Judge 必须解释保留或丢弃原因，不能无声消失。
3. DeepAgents 工具摘要中的候选问题必须进入候选池：当前低级缺陷 Agent 摘要识别了 5 个候选，但最终只输出 1 个，信息在子图和专家输出之间丢失。
4. 对 Java/Spring payment benchmark 增加专项规则：SpEL、StandardEvaluationContext、BigDecimal.equals、Random/SecureRandom、静态缓存跨租户、CSV 注入、Content-Disposition、charset、ZipInputStream lifecycle。
5. Judge 去重不要把不同风险类型合并：认证问题、测试问题、性能问题可以同位置但不同类型；不能简单按位置过滤。
6. 对预埋清单中的“多维复合问题”拆分输出：如 ZIP 路径、大小、符号链接、mkdirs、资源关闭应分别输出，避免一个泛化 finding 覆盖过宽但漏掉关键细节。

## 结论

本轮真实检视证明平台链路已可用，但质量还不是生产级。当前严格召回率约 42.5%，假阳率约 40.0%，远低于目标。下一步应优先修复“候选丢失、源码幻觉、Judge 过度合并、Java/Spring 专项规则不足”四类问题，而不是继续增加更多专家数量。
