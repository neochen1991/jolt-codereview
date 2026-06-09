# PR5 / PR6 Review Quality Report After Stage 1

- Overall Recall: 0.9250 (37/40)
- Overall False Positive Rate: 0.0577 (3/52)
- Meets 90/10 Target: no

| PR | Run | Findings | Matched | Missing | Recall | FP | FP Rate | Tool Obs | Target |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| PR5 dynamic risk policy | `run_43616c17dbe64a46` | 23 | 17 | 3 | 0.8500 | 3 | 0.1304 | 9 | no |
| PR6 archive import/export | `run_ad3f2a565af94a8c` | 29 | 20 | 0 | 1.0000 | 0 | 0.0000 | 14 | yes |

## PR5 dynamic risk policy

- Status: waiting_confirmation
- Candidate Quality: `{"expert_candidate_count": 29, "verifier_accepted_count": 23, "verifier_rejected_count": 6, "verifier_rejected_reason_counts": {"evidence_not_in_source": 4, "source_contradicts_return_null": 1, "source_contradicts_bigdecimal_double_constructor": 1}, "tool_observation_count": 9, "tool_observation_rejected_not_on_diff_count": 0, "promoted_tool_candidate_count": 7, "judge_rejected_count": 11, "final_finding_count": 23, "candidate_rejected_count": 17}`
- Tool Observation States: `{"adopted_final": 8, "candidate": 1}`
- Tool Rules Hit: `{"config.static-rules.semgrep.java.jolt.jolt.java.sensitive-request-param-secret": 1, "jolt.java.reassign-merchant-ownership": 1, "config.static-rules.semgrep.java.jolt.jolt.java.static-mutable-collection": 1, "config.static-rules.semgrep.java.jolt.jolt.java.fixed-active-cache-key": 2, "config.static-rules.semgrep.java.spring.security.audit.spel-injection": 1, "config.static-rules.semgrep.java.jolt.jolt.java.failure-default-allow": 1, "config.static-rules.semgrep.java.jolt.jolt.java.bigdecimal-getter-equals-money": 1, "config.static-rules.semgrep.java.lang.security.audit.unsafe-reflection": 1}`

| ID | Expected Issue | Status | Best Match |
| --- | --- | --- | --- |
| PR5-01 | Hardcoded risk admin key | matched | 源码中硬编码管理密钥 (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:22) |
| PR5-02 | Admin key passed in query parameter | matched | 管理密钥通过 RequestParam 传输 (security_agent, src/main/java/com/joltbenchmark/payment/api/DynamicRiskPolicyController.java:27) |
| PR5-03 | User-controlled SpEL expression execution | matched | SpEL 表达式执行暴露完整 EvaluationContext (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:45) |
| PR5-04 | StandardEvaluationContext exposes PaymentOrder | matched | SpEL 表达式执行暴露完整 EvaluationContext (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:45) |
| PR5-05 | Request-controlled pluginClassName reflection | matched | 插件执行异常被吞掉并返回未拒绝结果 (coding_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:94) |
| PR5-06 | Plugin load failure defaults to allow | matched | 安全或风控失败时默认放行 (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:47) |
| PR5-07 | Static HashMap policy cache is not thread safe | matched | 共享非线程安全对象 (coding_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:23) |
| PR5-08 | Fixed active cache key causes merchant overwrite | matched | 业务状态或缓存键缺少上下文隔离 (coding_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:86) |
| PR5-09 | lastPolicy global state pollutes tenants | matched | 保存策略使用固定 key 会覆盖所有商户策略 (coding_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:40) |
| PR5-10 | paymentId miss falls back to findAll first order | matched | 保存策略使用固定 key 会覆盖所有商户策略 (coding_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:40) |
| PR5-11 | evaluate does not verify merchant ownership | matched | 插件执行异常被吞掉并返回未拒绝结果 (coding_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:94) |
| PR5-12 | previewForMerchant leaks global payment summary | missing | - |
| PR5-13 | preview returns active policy from another merchant | matched | 业务状态或缓存键缺少上下文隔离 (coding_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:86) |
| PR5-14 | java.util.Random used for risk sampling | matched | 共享非线程安全对象 (coding_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:23) |
| PR5-15 | SecureRandom initialized with fixed seed | missing | - |
| PR5-16 | BigDecimal equals scale mismatch | matched | 金额 BigDecimal 使用 equals 比较，scale 不一致会导致误判 (low_level_defect_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:67) |
| PR5-17 | Default SpEL expression expands executable surface | matched | 未受信任的动态风控表达式被保存用于后续执行 (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:39) |
| PR5-18 | lastPolicyAgeSeconds can NPE | matched | 插件执行异常被吞掉并返回未拒绝结果 (coding_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:94) |
| PR5-19 | Policy priority is stored but ignored | missing | - |
| PR5-20 | Risk policy APIs lack real authz/audit approval | matched | 管理密钥通过 RequestParam 传输 (security_agent, src/main/java/com/joltbenchmark/payment/api/DynamicRiskPolicyController.java:27) |

Unmapped final findings:
- 风险插件直接依赖 PaymentOrder 聚合导致上下文模型耦合 (ddd_agent, src/main/java/com/joltbenchmark/payment/service/RiskPlugin.java:6)
- 风险策略表达式作为裸 String 存放缺少领域语义边界 (ddd_agent, src/main/java/com/joltbenchmark/payment/domain/DynamicRiskPolicy.java:7)
- 聚合归属或状态被外部任意改写 (ddd_agent, src/main/java/com/joltbenchmark/payment/domain/DynamicRiskPolicy.java:6)

## PR6 archive import/export

- Status: waiting_confirmation
- Candidate Quality: `{"expert_candidate_count": 35, "verifier_accepted_count": 35, "verifier_rejected_count": 0, "verifier_rejected_reason_counts": {}, "tool_observation_count": 14, "tool_observation_rejected_not_on_diff_count": 0, "promoted_tool_candidate_count": 12, "judge_rejected_count": 24, "final_finding_count": 29, "candidate_rejected_count": 24}`
- Tool Observation States: `{"candidate": 2, "adopted_final": 12}`
- Tool Rules Hit: `{"config.static-rules.semgrep.java.jolt.jolt.java.serializable-command-without-filter": 1, "config.static-rules.semgrep.java.jolt.jolt.java.zip-entry-write-without-normalize-guard": 2, "config.static-rules.semgrep.java.jolt.jolt.java.localdatetime-now-export-audit": 1, "config.static-rules.semgrep.java.jolt.jolt.java.regex-pattern-compile-user-input": 1, "config.static-rules.semgrep.java.jolt.jolt.java.content-disposition-unsanitized-filename": 1, "config.static-rules.semgrep.java.jolt.jolt.java.default-charset-csv-io": 3, "config.static-rules.semgrep.java.jolt.jolt.java.predictable-temp-file": 1, "config.static-rules.semgrep.java.jolt.jolt.java.zipinputstream-without-try-resources": 1, "config.static-rules.semgrep.java.jolt.jolt.java.zip-processing-without-size-limit": 1, "config.static-rules.semgrep.java.jolt.jolt.java.zip-parent-mkdirs-unchecked": 1, "config.static-rules.semgrep.java.lang.security.audit.object-deserialization": 1}`

| ID | Expected Issue | Status | Best Match |
| --- | --- | --- | --- |
| PR6-01 | ObjectInputStream readObject unsafe deserialization | matched | 使用 ObjectInputStream 反序列化不可信对象 (security_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:90) |
| PR6-02 | Serializable command lacks whitelist/version/full validation | matched | 使用 ObjectInputStream 反序列化不可信对象 (security_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:90) |
| PR6-03 | ZipEntry name path traversal | matched | ZipInputStream 未使用 try-with-resources 释放 (performance_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:64) |
| PR6-04 | Destination request parameter allows arbitrary write directory | matched | 查询缺少分页限制，可能导致OOM或数据库压力 (database_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:35) |
| PR6-05 | ZIP extraction lacks size/count/ratio limits | matched | ZipInputStream 未使用 try-with-resources 释放 (performance_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:64) |
| PR6-06 | ZIP extraction does not reject symlink or special file | matched | 结算数据写入可预测临时文件可能泄露敏感信息 (security_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:56) |
| PR6-07 | mkdirs return value ignored | matched | 创建父目录失败时未显式中止 (coding_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:72) |
| PR6-08 | ZipInputStream not closed by try-with-resources | matched | ZipInputStream 未使用 try-with-resources 释放 (performance_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:64) |
| PR6-09 | User-controlled regex can cause ReDoS | matched | 用户可控正则表达式可能导致 ReDoS (security_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:34) |
| PR6-10 | payments.findAll filtered in memory | matched | 查询缺少分页限制，可能导致OOM或数据库压力 (database_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:35) |
| PR6-11 | CSV fields are not escaped | matched | Content-Disposition 使用未清洗文件名 (security_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:47) |
| PR6-12 | CSV formula injection | matched | Content-Disposition 使用未清洗文件名 (security_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:47) |
| PR6-13 | Content-Disposition filename not sanitized | matched | Content-Disposition 使用未清洗文件名 (security_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:47) |
| PR6-14 | fileName lacks separator/control/length validation | matched | 查询缺少分页限制，可能导致OOM或数据库压力 (database_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:35) |
| PR6-15 | outputDir allows arbitrary path write | matched | 查询缺少分页限制，可能导致OOM或数据库压力 (database_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:35) |
| PR6-16 | Default charset used for CSV IO | matched | 临时 CSV 写入未指定字符集 (coding_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:57) |
| PR6-17 | LocalDateTime.now lacks audit clock/zone | matched | 审计或导出时间缺少显式 Clock/时区 (coding_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:32) |
| PR6-18 | Predictable temp filename | matched | 结算数据写入可预测临时文件可能泄露敏感信息 (security_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:56) |
| PR6-19 | Corrections lack null/range/count validation | matched | 导入命令对象缺少字段级校验约束 (backend_agent, src/main/java/com/joltbenchmark/payment/service/ArchiveImportCommand.java:8) |
| PR6-20 | Archive import/export APIs lack authz and ownership | matched | 查询缺少分页限制，可能导致OOM或数据库压力 (database_agent, src/main/java/com/joltbenchmark/payment/service/SettlementArchiveService.java:35) |

Unmapped final findings:
- None
