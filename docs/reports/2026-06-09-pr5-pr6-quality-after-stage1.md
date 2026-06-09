# PR5 / PR6 Review Quality Report After Stage 1

- Overall Recall: 0.7500 (30/40)
- Overall False Positive Rate: 0.1143 (4/35)
- Meets 90/10 Target: no

| PR | Run | Findings | Matched | Missing | Recall | FP | FP Rate | Tool Obs | Target |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| PR5 dynamic risk policy | `run_bbd179dedde447eb` | 23 | 16 | 4 | 0.8000 | 3 | 0.1304 | 7 | no |
| PR6 archive import/export | `run_d9b1f9a91f334727` | 12 | 14 | 6 | 0.7000 | 1 | 0.0833 | 6 | no |

## PR5 dynamic risk policy

- Status: waiting_confirmation
- Candidate Quality: `{"expert_candidate_count": 27, "verifier_accepted_count": 27, "verifier_rejected_count": 0, "verifier_rejected_reason_counts": {}, "tool_observation_count": 7, "tool_observation_rejected_not_on_diff_count": 0, "promoted_tool_candidate_count": 5, "judge_rejected_count": 14, "final_finding_count": 23, "candidate_rejected_count": 14}`
- Tool Observation States: `{"adopted_final": 5, "candidate": 2}`
- Tool Rules Hit: `{"jolt.java.reassign-merchant-ownership": 1, "config.static-rules.semgrep.java.jolt.jolt.java.static-mutable-collection": 1, "config.static-rules.semgrep.java.jolt.jolt.java.fixed-active-cache-key": 2, "config.static-rules.semgrep.java.spring.security.audit.spel-injection": 1, "config.static-rules.semgrep.java.jolt.jolt.java.failure-default-allow": 1, "config.static-rules.semgrep.java.lang.security.audit.unsafe-reflection": 1}`

| ID | Expected Issue | Status | Best Match |
| --- | --- | --- | --- |
| PR5-01 | Hardcoded risk admin key | matched | 硬编码管理员密钥 (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:22) |
| PR5-02 | Admin key passed in query parameter | missing | - |
| PR5-03 | User-controlled SpEL expression execution | matched | SpEL 表达式注入 (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:45) |
| PR5-04 | StandardEvaluationContext exposes PaymentOrder | missing | - |
| PR5-05 | Request-controlled pluginClassName reflection | matched | 插件加载异常被 printStackTrace 和 return null 吞掉 (low_level_defect_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:94) |
| PR5-06 | Plugin load failure defaults to allow | matched | 安全或风控失败时默认放行 (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:47) |
| PR5-07 | Static HashMap policy cache is not thread safe | matched | 固定缓存键导致跨商户策略覆盖 (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:40) |
| PR5-08 | Fixed active cache key causes merchant overwrite | matched | 策略保存使用固定缓存键，破坏 merchantId 级 API 契约 (backend_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:40) |
| PR5-09 | lastPolicy global state pollutes tenants | matched | 策略保存使用固定缓存键，破坏 merchantId 级 API 契约 (backend_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:40) |
| PR5-10 | paymentId miss falls back to findAll first order | matched | 安全或风控失败时默认放行 (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:47) |
| PR5-11 | evaluate does not verify merchant ownership | matched | 新增写接口缺少参数校验，策略表达式和优先级可接受非法值 (backend_agent, src/main/java/com/joltbenchmark/payment/api/DynamicRiskPolicyController.java:25) |
| PR5-12 | previewForMerchant leaks global payment summary | matched | 风险评估在找不到指定支付单时回退到其他支付单，破坏聚合身份不变量 (ddd_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:47) |
| PR5-13 | preview returns active policy from another merchant | matched | 策略保存使用固定缓存键，破坏 merchantId 级 API 契约 (backend_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:40) |
| PR5-14 | java.util.Random used for risk sampling | matched | 共享非线程安全对象 (coding_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:23) |
| PR5-15 | SecureRandom initialized with fixed seed | missing | - |
| PR5-16 | BigDecimal equals scale mismatch | matched | BigDecimal 通过 doubleValue 重新构造会引入精度误差 (low_level_defect_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:53) |
| PR5-17 | Default SpEL expression expands executable surface | matched | 保存风险策略时使用固定 active 键，破坏商户级策略边界 (ddd_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:40) |
| PR5-18 | lastPolicyAgeSeconds can NPE | matched | 策略保存使用固定缓存键，破坏 merchantId 级 API 契约 (backend_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:40) |
| PR5-19 | Policy priority is stored but ignored | missing | - |
| PR5-20 | Risk policy APIs lack real authz/audit approval | matched | 硬编码管理员密钥 (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:22) |

Unmapped final findings:
- 风险策略的关键业务概念长期使用裸基础类型表达 (ddd_agent, src/main/java/com/joltbenchmark/payment/domain/DynamicRiskPolicy.java:6)
- 风险插件直接依赖 PaymentOrder 聚合实体，耦合风控上下文和支付上下文 (ddd_agent, src/main/java/com/joltbenchmark/payment/service/RiskPlugin.java:6)
- 聚合归属或状态被外部任意改写 (ddd_agent, src/main/java/com/joltbenchmark/payment/domain/DynamicRiskPolicy.java:6)

## PR6 archive import/export

- Status: waiting_confirmation
- Candidate Quality: `{"expert_candidate_count": 19, "verifier_accepted_count": 19, "verifier_rejected_count": 0, "verifier_rejected_reason_counts": {}, "tool_observation_count": 6, "tool_observation_rejected_not_on_diff_count": 0, "promoted_tool_candidate_count": 4, "judge_rejected_count": 16, "final_finding_count": 12, "candidate_rejected_count": 16}`
- Tool Observation States: `{"adopted_final": 5, "candidate": 1}`
- Tool Rules Hit: `{"config.static-rules.semgrep.java.jolt.jolt.java.zip-entry-write-without-normalize-guard": 2, "config.static-rules.semgrep.java.jolt.jolt.java.content-disposition-unsanitized-filename": 1, "config.static-rules.semgrep.java.jolt.jolt.java.zip-processing-without-size-limit": 1, "config.static-rules.semgrep.java.lang.security.audit.object-deserialization": 1, "config.static-rules.semgrep.java.jolt.jolt.java.objectinputstream-readobject": 1}`

| ID | Expected Issue | Status | Best Match |
| --- | --- | --- | --- |
| PR6-01 | ObjectInputStream readObject unsafe deserialization | matched | 使用 ObjectInputStream 反序列化不可信对象 (security_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:90) |
| PR6-02 | Serializable command lacks whitelist/version/full validation | matched | 使用 ObjectInputStream 反序列化不可信对象 (security_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:90) |
| PR6-03 | ZipEntry name path traversal | matched | ZIP 导入循环没有条目数和解压总量边界 (performance_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:66) |
| PR6-04 | Destination request parameter allows arbitrary write directory | matched | ZIP 解压目标路径未规范化校验导致 Zip Slip 风险 (security_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:67) |
| PR6-05 | ZIP extraction lacks size/count/ratio limits | matched | ZIP 解压缺少条目数和总字节数限制 (security_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:66) |
| PR6-06 | ZIP extraction does not reject symlink or special file | matched | ZIP 导入循环没有条目数和解压总量边界 (performance_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:66) |
| PR6-07 | mkdirs return value ignored | missing | - |
| PR6-08 | ZipInputStream not closed by try-with-resources | matched | ZIP 导入循环没有条目数和解压总量边界 (performance_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:66) |
| PR6-09 | User-controlled regex can cause ReDoS | missing | - |
| PR6-10 | payments.findAll filtered in memory | matched | 查询缺少分页和结果上限 (database_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:35) |
| PR6-11 | CSV fields are not escaped | missing | - |
| PR6-12 | CSV formula injection | matched | 下载响应文件名未净化 (security_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:48) |
| PR6-13 | Content-Disposition filename not sanitized | matched | 下载响应文件名未净化 (security_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:48) |
| PR6-14 | fileName lacks separator/control/length validation | matched | 查询缺少分页和结果上限 (database_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:35) |
| PR6-15 | outputDir allows arbitrary path write | matched | ZIP 解压写文件缺少路径归一化保护 (security_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:64) |
| PR6-16 | Default charset used for CSV IO | matched | 导出接口全量加载订单并一次性构建 CSV，存在容量和延迟风险 (performance_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:35) |
| PR6-17 | LocalDateTime.now lacks audit clock/zone | missing | - |
| PR6-18 | Predictable temp filename | missing | - |
| PR6-19 | Corrections lack null/range/count validation | missing | - |
| PR6-20 | Archive import/export APIs lack authz and ownership | matched | 新增结算归档接口缺少认证控制 (security_agent, src/main/java/com/joltbenchmark/payment/api/ArchiveImportController.java:23) |

Unmapped final findings:
- POST 写接口缺少幂等防重机制 (backend_agent, src/main/java/com/joltbenchmark/payment/api/ArchiveImportController.java:33)
