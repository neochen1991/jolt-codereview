# Java Rare Business MR Review Quality Report

- MR: mr_repo_github_java_rare_business_9601
- Review Run: run_c908b90affd94d97
- Run Status: waiting_confirmation
- Expected Issues: 13
- Candidate Findings: 130
- Candidate Strict Recall: 100.0%
- Candidate Strict False Positive Rate: 63.8%
- Final Findings: 11
- Strict Matched Issues: 10
- Strict Missing Issues: 3
- Strict False Positive Findings: 1
- Strict Recall: 76.9%
- Strict False Positive Rate: 9.1%
- Rule-Level Matched Issues: 11
- Rule-Level Recall: 84.6%
- Meets Target: yes
- Trace Complete: yes
- Suggested Code Complete: yes
- Evidence Contract Complete: yes
- Evidence Contract Avg Score: 100.0%
- Evidence Contract Risk: ok

## Runtime Diagnosis

- Terminal Run: yes
- Reached Verify: yes
- Reached Judge: yes
- Reached Finalize: no
- Static Tool Summary: 外部静态工具可用 15 个，产出 62 个候选观察
- Expert Candidate Events: 9
- Expert Candidate Total: 58

### Expert Candidate Events

| Agent | Candidates | Time | Summary |
| --- | ---: | --- | --- |
| security_agent | 10 | 2026-06-16 13:35:25 | security_agent 产出 10 个候选问题 |
| dependency_agent | 2 | 2026-06-16 13:37:07 | dependency_agent 产出 2 个候选问题 |
| database_agent | 4 | 2026-06-16 13:38:37 | database_agent 产出 4 个候选问题 |
| performance_agent | 6 | 2026-06-16 13:39:48 | performance_agent 产出 6 个候选问题 |
| ddd_agent | 12 | 2026-06-16 13:41:57 | ddd_agent 产出 12 个候选问题 |
| backend_agent | 8 | 2026-06-16 13:43:51 | backend_agent 产出 8 个候选问题 |
| low_level_defect_agent | 3 | 2026-06-16 13:46:03 | low_level_defect_agent 产出 3 个候选问题 |
| coding_agent | 5 | 2026-06-16 13:47:04 | coding_agent 产出 5 个候选问题 |
| test_agent | 8 | 2026-06-16 13:48:35 | test_agent 产出 8 个候选问题 |

### Recent Trace Events

| Time | Span | Event | Summary |
| --- | --- | --- | --- |
| 2026-06-16 13:49:58 | judge_findings | finding_deduped | 合并 5 个同文件同行重复问题 |
| 2026-06-16 13:49:58 | judge_findings | finding_pruned | 收敛 16 个低信号或已覆盖的最终问题 |
| 2026-06-16 13:49:58 | judge_findings | finding_dropped | 高危 CVE 依赖必须阻断 被 Judge 过滤：deduped_lower_rank |
| 2026-06-16 13:49:58 | judge_findings | finding_dropped | ThreadLocal 变量未在 finally 块清理 被 Judge 过滤：deduped_lower_rank |
| 2026-06-16 13:49:58 | judge_findings | finding_dropped | Controller使用裸Map接收请求违反贫血模型原则 被 Judge 过滤：weak_unbacked_ddd_design_evidence |
| 2026-06-16 13:49:58 | judge_findings | finding_dropped | 审计仓储接口使用字符串存储违反领域事件语义 被 Judge 过滤：weak_unbacked_ddd_design_evidence |
| 2026-06-16 13:49:58 | judge_findings | finding_dropped | 网关回执record暴露原始数据违反领域语义 被 Judge 过滤：weak_unbacked_ddd_design_evidence |
| 2026-06-16 13:49:58 | judge_findings | finding_dropped | 应用服务构造函数注入过多依赖违反单一职责 被 Judge 过滤：weak_unbacked_ddd_design_evidence |
| 2026-06-16 13:49:58 | judge_findings | finding_dropped | ThreadLocal 未清理导致租户上下文泄漏 被 Judge 过滤：deduped_lower_rank |
| 2026-06-16 13:49:58 | judge_findings | finding_dropped | forcePay 接口入参缺少校验且未使用类型化 DTO 被 Judge 过滤：deduped_lower_rank |
| 2026-06-16 13:49:58 | judge_findings | finding_dropped | ThreadLocal 设置后未清理导致租户上下文泄漏 被 Judge 过滤：deduped_lower_rank |
| 2026-06-16 13:49:58 | judge_findings | finding_dropped | bulkRisk 接口直接接受 List<String> 无边界限制 被 Judge 过滤：deduped_lower_rank |
| 2026-06-16 13:49:58 | judge_findings | finding_dropped | @RequestBody Map<String,Object> 缺乏参数校验导致非法输入直接穿透 被 Judge 过滤：deduped_lower_rank |
| 2026-06-16 13:49:58 | judge_findings | finding_dropped | 使用 Map<String,Object> 接收请求体缺少输入验证 被 Judge 过滤：deduped_lower_rank |
| 2026-06-16 13:49:58 | judge_findings | finding_dropped | Map 入参字段缺少显式空值和类型校验 被 Judge 过滤：deduped_lower_rank |
| 2026-06-16 13:49:58 | judge_findings | finding_dropped | 使用Map<String,Object>存储扩展字段违反值对象建模 被 Judge 过滤：deduped_lower_rank |
| 2026-06-16 13:49:58 | judge_findings | finding_dropped | 接口 RequestBody 缺少 Bean Validation 被 Judge 过滤：deduped_lower_rank |
| 2026-06-16 13:49:58 | judge_findings | finding_dropped | 引入存在远程代码执行漏洞的 Fastjson 版本 被 Judge 过滤：deduped_lower_rank |
| 2026-06-16 13:49:58 | judge_findings | finding_dropped | SpEL表达式解析违反领域模型纯度 被 Judge 过滤：deduped_lower_rank |
| 2026-06-16 13:49:58 | judge_findings | finding_dropped | forcePay 参数校验缺失且无测试覆盖 被 Judge 过滤：auxiliary_overlap_core_issue |

## Expected Issue Coverage

| Rule | Status | File | Line | Title |
| --- | --- | --- | ---: | --- |
| SEC-AUTHZ-002 | final=matched / candidate | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 24 | forcePay 使用请求 tenantId/merchantId 未校验资源归属 |
| BE-IDEMP-004 | final=missing / candidate | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 22 | forcePay 副作用接口缺少幂等保护 |
| BE-API-001 | final=matched / candidate | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 31 | bulkRisk 接收无校验 List 请求体 |
| DDD-AGG-001 | final=missing / candidate | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 34 | SettlementLedger 状态和商户归属被外部任意覆盖 |
| BE-TX-002 | final=matched / candidate | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 38 | 事务内调用外部打款网关 |
| SEC-SECRET-004 | final=matched / candidate | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 39 | 审计日志和响应暴露银行卡号和网关原文 |
| PERF-QUERY-001 | final=matched / candidate | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 49 | bulk risk 循环内逐条远程调用 |
| SEC-INJECT-003 | final=matched / candidate | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 57 | SpEL 表达式来自外部输入可执行 |
| CODE-STATE-004 | final=matched / candidate | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 31 | ThreadLocal 租户上下文未清理 |
| PERF-MEM-004 | final=matched / candidate | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 65 | findAll 导出无界结果集进入内存 |
| DB-NOTNULL-002 | final=matched / candidate | src/main/resources/db/migration/V20260616__rare_settlement.sql | 1 | 新增 NOT NULL 列缺少默认值和回填 |
| DB-DDL-001 | final=matched / candidate | src/main/resources/db/migration/V20260616__rare_settlement.sql | 2 | 迁移脚本直接 DROP COLUMN |
| DEP-CVE-001 | final=missing / candidate | pom.xml | 10 | fastjson 1.2.47 已知漏洞 |

## Candidate Findings

| Stage | Status | Rule(s) | Severity | Confidence | Source | File | Line | Title |
| --- | --- | --- | --- | ---: | --- | --- | ---: | --- |
| judge | final | CODE-STATE-004, LLDOC-CONC-107, PERF-THREAD-005 | high | 0.99 | security_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 32 | ThreadLocal 写入后未清理导致跨请求数据泄漏 |
| judge | final | BE-IDEMP-004, BE-API-001 | high | 0.9700000000000001 | backend_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 30 | POST 副作用接口缺少幂等保护 |
| judge | final | DB-NOTNULL-002, DB-NOTNULL-008 | medium | 0.93 | database_agent | src/main/resources/db/migration/V20260616__rare_settlement.sql | 1 | 新增 NOT NULL 列缺少默认值 |
| judge | final | SEC-INJECT-003 | high | 0.92 | security_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 56 | 使用 StandardEvaluationContext 解析 SpEL 表达式存在注入风险 |
| judge | final | DB-DDL-007, DB-DDL-001 | high | 0.9 | database_agent | src/main/resources/db/migration/V20260616__rare_settlement.sql | 2 | 直接删除列违反灰度迁移规范 |
| judge | final | SEC-AUTHZ-002, SEC-AUTHN-001 | high | 0.88 | security_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 22 | 强制支付接口缺少认证和权限校验 |
| judge | final | PERF-MEM-004 | high | 0.87 | performance_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 66 | 结果集无上限累积到内存对象 |
| judge | final | SEC-SECRET-004 | high | 0.86 | security_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 42 | 配置或代码中包含明文密钥 |
| judge | final | PERF-QUERY-001 | high | 0.86 | performance_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 50 | 查询缺少分页或结果上限 |
| judge | final | BE-TX-002 | medium | 0.82 | performance_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 36 | @Transactional 内执行外部 IO 导致事务时间过长 |
| judge | final | BE-TX-002 | high | 0.8 | backend_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 14 | 覆盖商户 ID 操作破坏结算单归属不变性 |
| verifier | accepted | SEC-AUTHZ-002, SEC-AUTHN-001 | critical | 0.95 | security_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 22 | 强制支付接口缺少认证和权限校验 |
| verifier | accepted | CODE-STATE-004, BE-ERR-003 | high | 0.95 | backend_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 32 | ThreadLocal 未清理导致租户上下文泄漏 |
| verifier | accepted | TEST-COVER-001, TEST-SLICE-004 | high | 0.95 | test_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 22 | forcePay 接口缺少测试覆盖 |
| verifier | accepted | TEST-COVER-001, TEST-BOUND-003 | high | 0.95 | test_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 30 | bulkRisk 接口缺少测试覆盖 |
| verifier | accepted | TEST-COVER-001, TEST-ASSERT-002 | high | 0.95 | test_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 31 | forcePay 核心业务逻辑缺少单元测试 |
| verifier | accepted | DB-NOTNULL-002, DB-NOTNULL-008 | medium | 0.93 | database_agent | src/main/resources/db/migration/V20260616__rare_settlement.sql | 1 | 新增 NOT NULL 列缺少默认值 |
| verifier | accepted | DEP-CVE-001, SEC-DESER-005 | critical | 0.92 | security_agent | pom.xml | 6 | 引入存在远程代码执行漏洞的 Fastjson 版本 |
| verifier | accepted | DEP-CVE-001, DEP-SCOPE-005 | medium | 0.92 | dependency_agent | pom.xml | 10 | 测试依赖 scope 必须最小化 |
| verifier | accepted | PERF-QUERY-001, PERF-NPLUS1-002 | high | 0.92 | performance_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 31 | 批量风险接口无界请求导致 OOM 风险 |
| verifier | accepted | DDD-AGG-002, DDD-AGG-001, DDD-AGG-008 | high | 0.92 | ddd_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 16 | 聚合不变量被外部裸setter绕过 |
| verifier | accepted | forcePay 接口入参缺少校验且未使用类型化 DTO, CODE-NULL-001, BE-API-001 | high | 0.92 | backend_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 22 | forcePay 接口入参缺少校验且未使用类型化 DTO |
| verifier | accepted | CODE-STATE-004, SEC-AUTHZ-002 | high | 0.9 | security_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 32 | ThreadLocal 写入后未清理导致跨请求数据泄漏 |
| verifier | accepted | PERF-QUERY-001, DB-QUERY-002 | high | 0.9 | database_agent | src/main/java/com/acme/settlement/service/SettlementRepository.java | 6 | findAll 方法缺少分页边界 |
| verifier | accepted | DB-DDL-001, DB-DDL-007 | high | 0.9 | database_agent | src/main/resources/db/migration/V20260616__rare_settlement.sql | 2 | 直接删除列违反灰度迁移规范 |
| verifier | accepted | TEST-COVER-001, TEST-BOUND-003 | high | 0.9 | test_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 14 | overrideMerchant 权限路径缺少测试 |
| verifier | accepted | SEC-INJECT-003 | high | 0.88 | security_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 56 | 使用 StandardEvaluationContext 解析 SpEL 表达式存在注入风险 |
| verifier | accepted | 高危 CVE 依赖必须阻断, DEP-CVE-001 | critical | 0.88 | dependency_agent | pom.xml | 5 | 高危 CVE 依赖必须阻断 |
| verifier | accepted | DDD-AGG-009, DDD-CTX-004 | high | 0.88 | ddd_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 14 | 聚合方法命名违反通用语言原则 |
| verifier | accepted | BE-TX-002 | high | 0.88 | backend_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 14 | 覆盖商户 ID 操作破坏结算单归属不变性 |
| verifier | accepted | CODE-STATE-004, LLDOC-CONC-107 | high | 0.88 | low_level_defect_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 32 | ThreadLocal 泄漏风险 - set 后未 remove |
| verifier | accepted | TEST-COVER-001, TEST-ASSERT-002 | medium | 0.88 | test_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 56 | isPromotionOpen SpEL 表达式逻辑缺少测试 |
| verifier | accepted | CODE-STATE-004, PERF-THREAD-005 | high | 0.86 | performance_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 32 | ThreadLocal 资源泄漏 |
| verifier | accepted | DDD-AGG-002, DDD-AGG-001, DDD-CTX-005 | high | 0.86 | ddd_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 31 | 应用服务绕过聚合方法直接修改内部状态 |
| verifier | accepted | CODE-STATE-004, CODE-RESOURCE-005 | medium | 0.86 | coding_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 31 | ThreadLocal 设置后未清理导致租户上下文泄漏 |
| verifier | accepted | SEC-SECRET-004 | high | 0.85 | security_agent | src/main/java/com/acme/settlement/service/PayoutReceipt.java | 1 | 结算凭证记录银行卡号和原始网关消息存在信息泄漏风险 |
| verifier | accepted | CODE-STATE-004, BE-TX-002 | medium | 0.85 | database_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 31 | ThreadLocal 变量未在 finally 块清理 |
| verifier | accepted | 使用 Map<String,Object> 接收请求体缺少输入验证, CODE-NULL-001, SEC-AUTHN-001 | medium | 0.82 | security_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 23 | 使用 Map<String,Object> 接收请求体缺少输入验证 |
| verifier | accepted | BE-TX-002, PERF-THREAD-005 | medium | 0.82 | performance_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 36 | @Transactional 内执行外部 IO 导致事务时间过长 |
| verifier | accepted | DDD-VO-002, CODE-NULL-001, DDD-VO-001 | medium | 0.82 | ddd_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 10 | 使用Map<String,Object>存储扩展字段违反值对象建模 |
| verifier | accepted | DDD-CTX-005 | medium | 0.82 | ddd_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 23 | Controller使用裸Map接收请求违反贫血模型原则 |
| verifier | accepted | BE-IDEMP-004 | medium | 0.82 | backend_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 23 | 强 制支付接口缺少幂等保护 |
| verifier | accepted | CODE-BOUND-002 | medium | 0.82 | coding_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 31 | bulkRisk 接口直接接受 List<String> 无边界限制 |
| verifier | accepted | DDD-CTX-005 | medium | 0.8 | ddd_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 32 | ThreadLocal存储租户ID违反多租户隔离语义 |
| verifier | accepted | CODE-EXC-003, BE-ERR-003 | medium | 0.8 | backend_agent | src/main/java/com/acme/settlement/service/PayoutReceipt.java | 1 | 网关响应原始数据直接存储存在信息泄漏风险 |
| verifier | accepted | TEST-BOUND-003, TEST-ASSERT-002, TEST-SLICE-004 | medium | 0.8 | test_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 23 | forcePay 参数校验缺失且无测试覆盖 |
| verifier | accepted | DDD-AGG-009 | medium | 0.78 | ddd_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 56 | SpEL表达式解析违反领域模型纯度 |
| verifier | accepted | DDD-CTX-004 | medium | 0.78 | ddd_agent | src/main/java/com/acme/settlement/service/AuditRepository.java | 3 | 审计仓储接口使用字符串存储违反领域事件语义 |
| verifier | accepted | CODE-NULL-001, CODE-BOUND-002 | medium | 0.78 | coding_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 23 | @RequestBody Map<String,Object> 缺乏参数校验导致非法输入直接穿透 |
| verifier | accepted | DDD-CTX-003 | low | 0.75 | ddd_agent | src/main/java/com/acme/settlement/service/PayoutReceipt.java | 2 | 网关回执record暴露原始数据违反领域语义 |
| verifier | accepted | DDD-CTX-005 | low | 0.72 | ddd_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 19 | 应用服务构造函数注入过多依赖违反单一职责 |
| tool_promotion | candidate | DEP-CVE-001 | high | 0.9 | dependency_agent | pom.xml | 9 | 依赖组件存在已知漏洞 |
| tool_promotion | candidate | BE-IDEMP-004 | high | 0.88 | backend_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 30 | POST 副作用接口缺少幂等保护 |
| tool_promotion | candidate | TEST-COVER-001 | medium | 0.88 | test_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 1 | MR 新增 Java 业务代码，但 diff 中没有对应测试文件，关键业务路径缺少回归验证信号。
Evidence: 新增 src/main/java 代码且未 |
| tool_promotion | candidate | BE-API-001 | medium | 0.87 | backend_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 31 | 接口 RequestBody 缺少 Bean Validation |
| tool_promotion | candidate | PERF-MEM-004 | high | 0.87 | performance_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 66 | 结果集无上限累积到内存对象 |
| tool_promotion | candidate | DDD-AGG-001 | high | 0.86 | ddd_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 14 | 聚合归属或状态被外部任意改写 |
| tool_promotion | candidate | SEC-SECRET-004 | high | 0.86 | security_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 39 | 配置或代码中包含明文密钥 |
| tool_promotion | candidate | SEC-SECRET-004 | high | 0.86 | security_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 42 | 配置或代码中包含明文密钥 |
| tool_promotion | candidate | PERF-QUERY-001 | high | 0.86 | performance_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 50 | 查询缺少分页或结果上限 |
| tool_promotion | candidate | DDD-AGG-004, DDD-AGG-001 | medium | 0.85 | ddd_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 18 | 聚合边界或业务不变量表达不完整 |
| tool_promotion | candidate | DDD-AGG-004, DDD-AGG-001 | medium | 0.85 | ddd_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 22 | 聚合边界或业务不变量表达不完整 |
| bound_rule_supplement | candidate | 聚合必须维护自身不变量, DDD-AGG-001 | medium | 0.8 | ddd_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 35 | 聚合必须维护自身不变量 |
| tool_promotion | candidate | BE-API-001 | medium | 0.8 | backend_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 22 | 接口 RequestBody 缺少 Bean Validation |
| tool_promotion | candidate | CODE-NULL-001 | medium | 0.8 | coding_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 26 | Map 入参字段缺少显式空值和类型校验 |
| tool_promotion | candidate | BE-API-001 | medium | 0.8 | backend_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 30 | 接口 RequestBody 缺少 Bean Validation |
| tool_promotion | candidate | DDD-VO-002, CODE-NULL-001 | medium | 0.8 | ddd_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 12 | 领域模型使用弱类型 Map 表达业务属性 |
| judge | rejected | DEP-CVE-001, DEP-SCOPE-005, SEC-DESER-005 | high | 0.99 | dependency_agent | pom.xml | 9 | 依赖组件存在已知漏洞 |
| judge | rejected | CODE-NULL-001, BE-API-001, CODE-BOUND-002, SEC-AUTHN-001 | medium | 0.9700000000000001 | coding_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 24 | Map 入参字段缺少显式空值和类型校验 |
| verifier | rejected | BE-TX-002, BE-INTEGRATION-006 | high | 0.9500000000000001 | backend_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 31 | 事务内执行外部支付网关调用违反隔离原则 |
| judge | rejected | DEP-CVE-001, SEC-DESER-005 | critical | 0.9500000000000001 | security_agent | pom.xml | 6 | 引入存在远程代码执行漏洞的 Fastjson 版本 |
| judge | rejected | 聚合必须维护自身不变量, DDD-AGG-001, DDD-AGG-009 | medium | 0.9500000000000001 | ddd_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 35 | 聚合必须维护自身不变量 |
| verifier | rejected | SEC-AUTHZ-002, SEC-AUTHN-001 | critical | 0.95 | security_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 30 | 批量风险接口缺少认证和权限校验 |
| judge | rejected | TEST-COVER-001, TEST-ASSERT-002 | high | 0.95 | test_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 31 | forcePay 核心业务逻辑缺少单元测试 |
| judge | rejected | TEST-COVER-001, TEST-BOUND-003 | high | 0.95 | test_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 30 | bulkRisk 接口缺少测试覆盖 |
| judge | rejected | 使用 Map<String,Object> 接收请求体缺少输入验证, BE-API-001, CODE-BOUND-002, CODE-NULL-001, SEC-AUTHN-001 | medium | 0.9400000000000001 | security_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 23 | 使用 Map<String,Object> 接收请求体缺少输入验证 |
| verifier | rejected | CODE-NULL-001, LLDOC-NULL-101, LLDEF-NULL-001 | high | 0.92 | low_level_defect_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 33 | NPE 风险 - Repository 查询结果未判空直接解引用 |
| judge | rejected | CODE-STATE-004, BE-ERR-003 | high | 0.92 | backend_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 32 | ThreadLocal 未清理导致租户上下文泄漏 |
| judge | rejected | DDD-AGG-009 | medium | 0.92 | ddd_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 56 | SpEL表达式解析违反领域模型纯度 |
| judge | rejected | CODE-STATE-004, PERF-THREAD-005 | high | 0.92 | performance_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 32 | ThreadLocal 资源泄漏 |
| judge | rejected | CODE-STATE-004, LLDOC-CONC-107 | high | 0.92 | low_level_defect_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 32 | ThreadLocal 泄漏风险 - set 后未 remove |
| judge | rejected | DEP-CVE-001, DEP-SCOPE-005 | medium | 0.92 | dependency_agent | pom.xml | 10 | 测试依赖 scope 必须最小化 |
| judge | rejected | DDD-CTX-005 | medium | 0.92 | ddd_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 32 | ThreadLocal存储租户ID违反多租户隔离语义 |
| judge | rejected | TEST-COVER-001, TEST-ASSERT-002 | medium | 0.92 | test_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 56 | isPromotionOpen SpEL 表达式逻辑缺少测试 |
| judge | rejected | TEST-COVER-001, TEST-BOUND-003 | high | 0.9 | test_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 14 | overrideMerchant 权限路径缺少测试 |
| verifier | rejected | PERF-TIMEOUT-003 | medium | 0.88 | performance_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 56 | 外部支付网关调用缺少超时配置 |
| verifier | rejected | PERF-TIMEOUT-003 | medium | 0.88 | performance_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 45 | 风险查询外部调用缺少超时配置 |
| verifier | rejected | BE-TX-002, BE-INTEGRATION-006 | high | 0.88 | backend_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 56 | 动态 SpEL 表达式解析存在注入风险 |
| judge | rejected | 高危 CVE 依赖必须阻断, DEP-CVE-001 | critical | 0.88 | dependency_agent | pom.xml | 5 | 高危 CVE 依赖必须阻断 |
| judge | rejected | forcePay 接口入参缺少校验且未使用类型化 DTO, CODE-NULL-001, BE-API-001 | high | 0.88 | backend_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 22 | forcePay 接口入参缺少校验且未使用类型化 DTO |
| judge | rejected | TEST-COVER-001, TEST-SLICE-004 | high | 0.88 | test_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 22 | forcePay 接口缺少测试覆盖 |
| judge | rejected | TEST-COVER-001 | medium | 0.88 | test_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 1 | MR 新增 Java 业务代码，但 diff 中没有对应测试文件，关键业务路径缺少回归验证信号。
Evidence: 新增 src/main/java 代码且未 |
| judge | rejected | CODE-BOUND-002, PERF-NPLUS1-002, PERF-QUERY-001 | high | 0.8700000000000001 | performance_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 31 | 批量风险接口无界请求导致 OOM 风险 |
| judge | rejected | BE-API-001 | medium | 0.87 | backend_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 31 | 接口 RequestBody 缺少 Bean Validation |
| judge | rejected | DDD-AGG-002, DDD-AGG-001, DDD-AGG-008 | high | 0.87 | ddd_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 16 | 聚合不变量被外部裸setter绕过 |
| judge | rejected | CODE-STATE-004, CODE-RESOURCE-005 | medium | 0.86 | coding_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 31 | ThreadLocal 设置后未清理导致租户上下文泄漏 |
| judge | rejected | DDD-AGG-002, DDD-AGG-001, DDD-CTX-005 | high | 0.86 | ddd_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 31 | 应用服务绕过聚合方法直接修改内部状态 |
| judge | rejected | SEC-SECRET-004 | high | 0.86 | security_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 39 | 配置或代码中包含明文密钥 |
| judge | rejected | DDD-AGG-001 | high | 0.86 | ddd_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 14 | 聚合归属或状态被外部任意改写 |
| verifier | rejected | PERF-NPLUS1-002 | medium | 0.85 | performance_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 40 | refreshRiskScores 循环内调用远程服务导致 N+1 |
| verifier | rejected | BE-TX-002, DDD-AGG-001, DDD-AGG-004, DDD-AGG-005 | medium | 0.85 | ddd_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 31 | 单个事务内修改多个聚合且无跨聚合一致性建模 |
| verifier | rejected | CODE-NULL-001, LLDOC-NULL-101 | medium | 0.85 | low_level_defect_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 24 | Map payload 缺失字段时产生 "null" 字符串导致下游异常 |
| verifier | rejected | Map payload 字段缺失时 String.valueOf 返回字面量 "null" 导致业务异常, CODE-NULL-001 | medium | 0.85 | coding_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 24 | Map payload 字段缺失时 String.valueOf 返回字面量 "null" 导致业务异常 |
| verifier | rejected | TEST-BOUND-003, TEST-ASSERT-002 | medium | 0.85 | test_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 7 | SettlementLedger 状态流转缺少边界场景测试 |
| judge | rejected | CODE-STATE-004, BE-TX-002 | medium | 0.85 | database_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 31 | ThreadLocal 变量未在 finally 块清理 |
| judge | rejected | PERF-QUERY-001, DB-QUERY-002 | high | 0.85 | database_agent | src/main/java/com/acme/settlement/service/SettlementRepository.java | 6 | findAll 方法缺少分页边界 |
| judge | rejected | DDD-VO-002, CODE-NULL-001, DDD-VO-001 | medium | 0.85 | ddd_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 12 | 领域模型使用弱类型 Map 表达业务属性 |
| judge | rejected | DDD-AGG-004, DDD-AGG-001 | medium | 0.85 | ddd_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 22 | 聚合边界或业务不变量表达不完整 |
| judge | rejected | DDD-AGG-004, DDD-AGG-001 | medium | 0.85 | ddd_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 18 | 聚合边界或业务不变量表达不完整 |
| judge | rejected | BE-API-001, CODE-NULL-001 | medium | 0.8300000000000001 | backend_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 30 | 接口 RequestBody 缺少 Bean Validation |
| verifier | rejected | TEST-BOUND-003, TEST-ASSERT-002 | medium | 0.82 | test_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 31 | forcePay 金额边界值缺少测试 |
| judge | rejected | DDD-VO-002, CODE-NULL-001, DDD-VO-001 | medium | 0.82 | ddd_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 10 | 使用Map<String,Object>存储扩展字段违反值对象建模 |
| judge | rejected | BE-IDEMP-004 | medium | 0.82 | backend_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 23 | 强 制支付接口缺少幂等保护 |
| verifier | rejected | SEC-AUTHZ-002 | medium | 0.8 | security_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 14 | 商户归属覆写方法缺少权限校验 |
| verifier | rejected | DDD-AGG-007 | medium | 0.8 | ddd_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 3 | 聚合根缺少工厂方法和完整构造函数 |
| verifier | rejected | findByMerchantId 返回值未做空值检查直接使用, CODE-NULL-001 | medium | 0.8 | coding_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 33 | findByMerchantId 返回值未做空值检查直接使用 |
| judge | rejected | CODE-NULL-001 | medium | 0.8 | coding_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 26 | Map 入参字段缺少显式空值和类型校验 |
| judge | rejected | DDD-AGG-009, DDD-CTX-004 | high | 0.8 | ddd_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 14 | 聚合方法命名违反通用语言原则 |
| verifier | rejected | SEC-AUTHZ-002 | medium | 0.78 | security_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 23 | 强制支付操作缺少幂等性保护 |
| verifier | rejected | 批量风险接口缺少参数验证和数量限制, SEC-AUTHN-001 | medium | 0.78 | security_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 31 | 批量风险接口缺少参数验证和数量限制 |
| judge | rejected | CODE-NULL-001, CODE-BOUND-002 | medium | 0.78 | coding_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 23 | @RequestBody Map<String,Object> 缺乏参数校验导致非法输入直接穿透 |
| judge | rejected | SEC-SECRET-004 | high | 0.77 | security_agent | src/main/java/com/acme/settlement/service/PayoutReceipt.java | 1 | 结算凭证记录银行卡号和原始网关消息存在信息泄漏风险 |
| judge | rejected | DDD-CTX-005 | medium | 0.7699999999999999 | ddd_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 23 | Controller使用裸Map接收请求违反贫血模型原则 |
| judge | rejected | CODE-EXC-003, BE-ERR-003 | medium | 0.75 | backend_agent | src/main/java/com/acme/settlement/service/PayoutReceipt.java | 1 | 网关响应原始数据直接存储存在信息泄漏风险 |
| judge | rejected | CODE-BOUND-002 | medium | 0.74 | coding_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 31 | bulkRisk 接口直接接受 List<String> 无边界限制 |
| judge | rejected | TEST-BOUND-003, TEST-ASSERT-002, TEST-SLICE-004 | medium | 0.7200000000000001 | test_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 23 | forcePay 参数校验缺失且无测试覆盖 |
| judge | rejected | DDD-CTX-004 | medium | 0.7000000000000001 | ddd_agent | src/main/java/com/acme/settlement/service/AuditRepository.java | 3 | 审计仓储接口使用字符串存储违反领域事件语义 |
| verifier | rejected | 批量风控接口入参校验不完整, BE-API-001 | low | 0.7 | backend_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 31 | 批量风控接口入参校验不完整 |
| judge | rejected | DDD-CTX-003 | low | 0.7 | ddd_agent | src/main/java/com/acme/settlement/service/PayoutReceipt.java | 2 | 网关回执record暴露原始数据违反领域语义 |
| judge | rejected | DDD-CTX-005 | low | 0.64 | ddd_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 19 | 应用服务构造函数注入过多依赖违反单一职责 |

## Candidate To Final Loss
- BE-IDEMP-004
- DDD-AGG-001
- DEP-CVE-001

## Final Findings

| Rule(s) | Severity | Confidence | Agent | File | Line | Title | Tool Count | Evidence Contract |
| --- | --- | ---: | --- | --- | ---: | --- | ---: | --- |
| DB-NOTNULL-002, DB-NOTNULL-008 | medium | 0.93 | database_agent | src/main/resources/db/migration/V20260616__rare_settlement.sql | 1 | 新增 NOT NULL 列缺少默认值 | 2 | satisfied:100.0% |
| BE-TX-002 | medium | 0.82 | performance_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 36 | @Transactional 内执行外部 IO 导致事务时间过长 | 2 | satisfied:100.0% |
| CODE-STATE-004, LLDOC-CONC-107, PERF-THREAD-005 | high | 0.99 | security_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 32 | ThreadLocal 写入后未清理导致跨请求数据泄漏 | 3 | satisfied:100.0% |
| BE-IDEMP-004, BE-API-001 | high | 0.9700000000000001 | backend_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 30 | POST 副作用接口缺少幂等保护 | 5 | satisfied:100.0% |
| SEC-INJECT-003 | high | 0.92 | security_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 56 | 使用 StandardEvaluationContext 解析 SpEL 表达式存在注入风险 | 4 | satisfied:100.0% |
| DB-DDL-001 | high | 0.9 | database_agent | src/main/resources/db/migration/V20260616__rare_settlement.sql | 2 | 直接删除列违反灰度迁移规范 | 3 | satisfied:100.0% |
| SEC-AUTHZ-002, SEC-AUTHN-001 | high | 0.88 | security_agent | src/main/java/com/acme/settlement/api/SettlementAdminController.java | 22 | 强制支付接口缺少认证和权限校验 | 2 | satisfied:100.0% |
| PERF-MEM-004 | high | 0.87 | performance_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 66 | 结果集无上限累积到内存对象 | 2 | satisfied:100.0% |
| SEC-SECRET-004 | high | 0.86 | security_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 42 | 配置或代码中包含明文密钥 | 4 | satisfied:100.0% |
| PERF-QUERY-001 | high | 0.86 | performance_agent | src/main/java/com/acme/settlement/service/SettlementPayoutService.java | 50 | 查询缺少分页或结果上限 | 2 | satisfied:100.0% |
| BE-TX-002 | high | 0.8 | backend_agent | src/main/java/com/acme/settlement/domain/SettlementLedger.java | 14 | 覆盖商户 ID 操作破坏结算单归属不变性 | 1 | satisfied:100.0% |

## Missing Rules
- BE-IDEMP-004
- DDD-AGG-001
- DEP-CVE-001

## Strict False Positives
- 覆盖商户 ID 操作破坏结算单归属不变性 (backend_agent, src/main/java/com/acme/settlement/domain/SettlementLedger.java:14) rules=BE-TX-002

## Tool Coverage

| Tool | Calls | Completed | Skipped | Failed | Hits | Rules Hit | Files Hit | Duration ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| deepagents.inspect_diff_summary | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| deepagents.inspect_static_observations | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| deepagents.list_skill_assets | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| deepagents.read_diff_patch | 9 | 9 | 0 | 0 | 0 | 0 | 0 | 0 |
| deepagents.read_skill_asset | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| git.prepare_source_worktree | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 8133 |
| github.fetch_file_contents | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 10181 |
| github.list_changed_files | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| static.bandit | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 155 |
| static.checkstyle | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 829 |
| static.dependency-check | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 925 |
| static.eslint | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 174 |
| static.gitleaks | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 31 |
| static.java_web_static | 1 | 1 | 0 | 0 | 20 | 15 | 4 | 0 |
| static.kics | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 186 |
| static.openapi-diff | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 195 |
| static.oss_prescan | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 148648 |
| static.osv-scanner | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 108524 |
| static.pmd | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 1808 |
| static.ruff | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 15 |
| static.semgrep | 4 | 4 | 0 | 0 | 11 | 8 | 4 | 16997 |
| static.semgrep.aggregate | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| static.spotbugs | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 336 |
| static.tree_sitter_code_graph | 1 | 1 | 0 | 0 | 5 | 3 | 2 | 7 |
| static.trivy | 1 | 1 | 0 | 0 | 13 | 13 | 1 | 9669 |

## Budget And Agents

- Agents Executed: backend_agent, coding_agent, database_agent, ddd_agent, dependency_agent, low_level_defect_agent, performance_agent, security_agent, test_agent
- LLM Calls: 13
- Tool Calls: 37
- Wall Seconds: 1148.041
- Truncated Reason: none
