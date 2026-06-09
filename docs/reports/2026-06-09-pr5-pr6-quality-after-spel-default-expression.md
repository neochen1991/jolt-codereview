# PR5 / PR6 Review Quality Report After Stage 1

- Overall Recall: 1.0000 (40/40)
- Overall False Positive Rate: 0.0000 (0/55)
- Meets 90/10 Target: yes

| PR | Run | Findings | Matched | Missing | Recall | FP | FP Rate | Tool Obs | Target |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| PR5 dynamic risk policy | `run_64a67e5b8db0468a` | 26 | 20 | 0 | 1.0000 | 0 | 0.0000 | 12 | yes |
| PR6 archive import/export | `run_ad3f2a565af94a8c` | 29 | 20 | 0 | 1.0000 | 0 | 0.0000 | 14 | yes |

## PR5 dynamic risk policy

- Status: waiting_confirmation
- Candidate Quality: `{"expert_candidate_count": 36, "verifier_accepted_count": 31, "verifier_rejected_count": 5, "verifier_rejected_reason_counts": {"evidence_not_in_source": 2, "source_has_empty_guard_for_first_element": 1, "source_contradicts_return_null": 2}, "tool_observation_count": 12, "tool_observation_rejected_not_on_diff_count": 0, "promoted_tool_candidate_count": 9, "judge_rejected_count": 18, "final_finding_count": 26, "candidate_rejected_count": 23}`
- Tool Observation States: `{"adopted_final": 11, "candidate": 1}`
- Tool Rules Hit: `{"config.static-rules.semgrep.java.jolt.jolt.java.sensitive-request-param-secret": 1, "config.static-rules.semgrep.java.jolt.jolt.java.policy-priority-stored-not-selected": 1, "config.static-rules.semgrep.java.jolt.jolt.java.static-mutable-collection": 1, "config.static-rules.semgrep.java.jolt.jolt.java.secure-random-fixed-seed": 1, "config.static-rules.semgrep.java.jolt.jolt.java.fixed-active-cache-key": 2, "config.static-rules.semgrep.java.spring.security.audit.spel-injection": 1, "config.static-rules.semgrep.java.jolt.jolt.java.failure-default-allow": 1, "config.static-rules.semgrep.java.jolt.jolt.java.spel-executable-default-expression": 1, "config.static-rules.semgrep.java.jolt.jolt.java.bigdecimal-getter-equals-money": 1, "config.static-rules.semgrep.java.jolt.jolt.java.preview-findall-cross-tenant-leak": 1, "config.static-rules.semgrep.java.lang.security.audit.unsafe-reflection": 1}`

| ID | Expected Issue | Status | Best Match |
| --- | --- | --- | --- |
| PR5-01 | Hardcoded risk admin key | matched | 源码中硬编码管理密钥 (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:22) |
| PR5-02 | Admin key passed in query parameter | matched | 管理密钥通过 URL 查询参数传入 (security_agent, src/main/java/com/joltbenchmark/payment/api/DynamicRiskPolicyController.java:27) |
| PR5-03 | User-controlled SpEL expression execution | matched | SpEL 表达式执行暴露完整 EvaluationContext (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:45) |
| PR5-04 | StandardEvaluationContext exposes PaymentOrder | matched | SpEL 表达式执行暴露完整 EvaluationContext (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:45) |
| PR5-05 | Request-controlled pluginClassName reflection | matched | 外部可控类名进入反射加载 (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:91) |
| PR5-06 | Plugin load failure defaults to allow | matched | 安全或风控失败时默认放行 (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:47) |
| PR5-07 | Static HashMap policy cache is not thread safe | matched | 风险策略使用固定缓存键造成跨商户策略污染 (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:40) |
| PR5-08 | Fixed active cache key causes merchant overwrite | matched | 策略缓存使用固定 active key 会让不同商户互相覆盖 (coding_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:40) |
| PR5-09 | lastPolicy global state pollutes tenants | matched | 商户预览接口忽略 merchantId 查询了全量订单 (backend_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:81) |
| PR5-10 | paymentId miss falls back to findAll first order | matched | 商户预览接口忽略 merchantId 查询了全量订单 (backend_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:81) |
| PR5-11 | evaluate does not verify merchant ownership | matched | 策略缓存使用固定 active key 会让不同商户互相覆盖 (coding_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:40) |
| PR5-12 | previewForMerchant leaks global payment summary | matched | 商户预览接口忽略 merchantId 查询了全量订单 (backend_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:81) |
| PR5-13 | preview returns active policy from another merchant | matched | 商户预览接口忽略 merchantId 查询了全量订单 (backend_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:81) |
| PR5-14 | java.util.Random used for risk sampling | matched | SecureRandom 使用固定种子导致随机值可预测 (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:25) |
| PR5-15 | SecureRandom initialized with fixed seed | matched | SecureRandom 使用固定种子导致随机值可预测 (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:25) |
| PR5-16 | BigDecimal equals scale mismatch | matched | 策略缓存使用固定 key 会让不同 merchantId 的策略互相覆盖 (low_level_defect_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:40) |
| PR5-17 | Default SpEL expression expands executable surface | matched | 默认 SpEL 表达式包含构造调用扩大执行攻击面 (security_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:52) |
| PR5-18 | lastPolicyAgeSeconds can NPE | matched | 策略缓存使用固定 active key 会让不同商户互相覆盖 (coding_agent, src/main/java/com/joltbenchmark/payment/service/DynamicRiskPolicyService.java:40) |
| PR5-19 | Policy priority is stored but ignored | matched | 策略优先级字段未参与决策选择 (ddd_agent, src/main/java/com/joltbenchmark/payment/domain/DynamicRiskPolicy.java:5) |
| PR5-20 | Risk policy APIs lack real authz/audit approval | matched | 管理密钥通过 URL 查询参数传入 (security_agent, src/main/java/com/joltbenchmark/payment/api/DynamicRiskPolicyController.java:27) |

Unmapped final findings:
- None

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
