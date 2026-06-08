# GitHub Payment Benchmark 3MR Quality Report

- Overall Recall: 0.9630
- Overall Invalid False Positive Rate: 0.0128
- Meets Target: no

| MR | Run | Expected | Matched | Missing | Findings | Invalid FP | Recall | FP Rate | Target |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| PR1 complex payment benchmark | `run_345ad33641f04dcd` | 17 | 15 | 2 | 27 | 0 | 0.8824 | 0.0000 | no |
| PR2 alternate payment benchmark | `run_4823a3a48d304bf1` | 17 | 17 | 0 | 25 | 0 | 1.0000 | 0.0000 | yes |
| PR3 ddd sql benchmark | `run_a3a1930d8b4d4fe3` | 20 | 20 | 0 | 26 | 1 | 1.0000 | 0.0385 | yes |

## PR1 complex payment benchmark

| ID | Expected Issue | Status | Best Match |
| --- | --- | --- | --- |
| 1 | Unauthenticated Admin Balance Adjustment | missing | - |
| 2 | Unsafe Negative and Arbitrary Balance Changes | matched | adjustBalance 余额写入缺少条件更新与版本号，存在并发覆盖与丢失更新风险 (src/main/java/com/joltbenchmark/payment/service/AccountService.java:44) |
| 3 | Sensitive Card Data Accepted and Stored | matched | PaymentOrder 实体明文存储完整卡号与 CVV (src/main/java/com/joltbenchmark/payment/domain/PaymentOrder.java:24) |
| 4 | Sensitive Card Data Returned in API Responses | matched | PaymentResponse 新增 cardNumber/cvv 字段无契约测试 (src/main/java/com/joltbenchmark/payment/api/dto/PaymentResponse.java:16) |
| 5 | Sensitive Data Logged | matched | 配置或代码中包含明文密钥 (src/main/java/com/joltbenchmark/payment/service/PaymentService.java:76) |
| 6 | Risk-Control Bypass Flag | matched | 客户端可控字段绕过风控 (src/main/java/com/joltbenchmark/payment/service/PaymentService.java:90) |
| 7 | Localhost IP Risk Bypass | matched | 客户端可控字段绕过风控 (src/main/java/com/joltbenchmark/payment/service/PaymentService.java:90) |
| 8 | Money Precision Loss | matched | BigDecimal 转换导致精度丢失 (src/main/java/com/joltbenchmark/payment/service/MoneyNormalizer.java:10) |
| 9 | Refund Allowed After Already Refunded | missing | - |
| 10 | Refund Amount Not Compared to Paid Amount or Prior Refunds | matched | Refund logic allows already-refunded payments; enforce refund state machine and  (src/main/java/com/joltbenchmark/payment/service/RefundService.java:43) |
| 11 | Weak Webhook Signature Trust | matched | 配置或代码中包含明文密钥 (src/main/java/com/joltbenchmark/payment/service/WebhookService.java:30) |
| 12 | Loose Webhook Event Matching | matched | 配置或代码中包含明文密钥 (src/main/java/com/joltbenchmark/payment/service/WebhookService.java:30) |
| 13 | Untrusted Callback URL Invocation | matched | 日志输出完整卡号、CVV 与回调 URL (src/main/java/com/joltbenchmark/payment/service/PaymentService.java:74) |
| 14 | Debug Endpoints Expose Internal Data | matched | 调试接口暴露支付、退款和 Webhook 全量数据且无任何鉴权 (src/main/java/com/joltbenchmark/payment/api/BenchmarkDebugController.java:15) |
| 15 | Stack Trace Leakage | matched | Server error config includes stack traces; disable stack traces in client respon (src/main/resources/application.yml:22) |
| 16 | SQL Logging Enabled in Application Config | matched | 生产配置暴露敏感运行时信息 (src/main/resources/application.yml:13) |
| 17 | Test Configuration Masks Missing Coverage | matched | Test configuration skips high-risk path tests; do not mask callback, auth, debug (src/test/resources/application-test.yml:24) |

Invalid false positives:
- None

## PR2 alternate payment benchmark

| ID | Expected Issue | Status | Best Match |
| --- | --- | --- | --- |
| PR2-01 | Export API Missing Auth And Ownership | matched | ExportController 缺失任何测试，导出权限路径与商户过滤逻辑无验证 (src/main/java/com/joltbenchmark/payment/api/ExportController.java:13) |
| PR2-02 | Export API Unbounded findAll | matched | ExportController 缺失任何测试，导出权限路径与商户过滤逻辑无验证 (src/main/java/com/joltbenchmark/payment/api/ExportController.java:13) |
| PR2-03 | Export merchantId Prefix/Null Risk | matched | ExportController 缺失任何测试，导出权限路径与商户过滤逻辑无验证 (src/main/java/com/joltbenchmark/payment/api/ExportController.java:13) |
| PR2-04 | Reconciliation Import Missing Auth | matched | 对账导入接口缺少认证授权，任何人都可篡改任意商户对账数据 (src/main/java/com/joltbenchmark/payment/api/ReconciliationController.java:21) |
| PR2-05 | Reconciliation rawCsv Null/Boundary | matched | ReconciliationService.importCsv 缺少异常处理与失败语义 (src/main/java/com/joltbenchmark/payment/service/ReconciliationService.java:16) |
| PR2-06 | Reconciliation Amount Parse Exception | matched | ReconciliationService.importCsv 缺少异常处理与失败语义 (src/main/java/com/joltbenchmark/payment/service/ReconciliationService.java:16) |
| PR2-07 | Reconciliation Raw CSV Audit Leak | matched | 对账审计日志写入用户可控原始 CSV，存在敏感信息与日志注入风险 (src/main/java/com/joltbenchmark/payment/service/ReconciliationService.java:28) |
| PR2-08 | Auto Settlement Full Scan/Long Transaction | matched | AutoSettlementService 定时结算分支缺失测试，状态流转与时间边界未验证 (src/main/java/com/joltbenchmark/payment/service/AutoSettlementService.java:22) |
| PR2-09 | Auto Settlement Missing Idempotency/Concurrency Guard | matched | AutoSettlementService 定时结算分支缺失测试，状态流转与时间边界未验证 (src/main/java/com/joltbenchmark/payment/service/AutoSettlementService.java:22) |
| PR2-10 | Payment Static Cache Consistency/Memory Risk | matched | PAYMENT_CACHE 静态 ConcurrentHashMap 缺少容量与失效策略 (src/main/java/com/joltbenchmark/payment/service/PaymentService.java:25) |
| PR2-11 | forceCapture Bypasses Payment State Machine | matched | Client-controlled forceCapture/force flag bypasses payment state checks; enforce (src/main/java/com/joltbenchmark/payment/service/PaymentService.java:80) |
| PR2-12 | PaymentAuditService Swallows IOException | matched | PaymentAuditService 直接吞掉 IOException 导致审计日志静默丢失 (src/main/java/com/joltbenchmark/payment/service/PaymentAuditService.java:18) |
| PR2-13 | Refund Manual Override State Bypass | matched | Refund reason MANUAL_OVERRIDE is user-controlled and bypasses paid-state validat (src/main/java/com/joltbenchmark/payment/service/RefundService.java:43) |
| PR2-14 | Refund reason Null NPE | matched | Refund reason MANUAL_OVERRIDE is user-controlled and bypasses paid-state validat (src/main/java/com/joltbenchmark/payment/service/RefundService.java:43) |
| PR2-15 | Webhook Dedupe Key Compatibility | matched | Webhook 去重主键从 eventId 变更为复合 key 破坏 webhook_event 表唯一性兼容 (src/main/java/com/joltbenchmark/payment/service/WebhookService.java:28) |
| PR2-16 | Weak Webhook Signature Trust | matched | 配置或代码中包含明文密钥 (src/main/java/com/joltbenchmark/payment/service/WebhookService.java:28) |
| PR2-17 | Webhook Sensitive Logging | matched | Webhook 日志和审计写入原始 payload 与 signature，泄漏敏感凭据 (src/main/java/com/joltbenchmark/payment/service/WebhookService.java:23) |

Invalid false positives:
- None

## PR3 ddd sql benchmark

| ID | Expected Issue | Status | Best Match |
| --- | --- | --- | --- |
| PR3-01 | DDD Controller Missing Auth | matched | DddReviewController 新增三个对外接口完全缺失测试覆盖 (src/main/java/com/joltbenchmark/payment/api/DddReviewController.java:15) |
| PR3-02 | Search merchantId IDOR | matched | DddReviewController 新增三个对外接口完全缺失测试覆盖 (src/main/java/com/joltbenchmark/payment/api/DddReviewController.java:15) |
| PR3-03 | Search Input Validation/Sort Whitelist | matched | search 方法通过字符串拼接构造 SQL，存在 SQL 注入与执行计划风险 (src/main/java/com/joltbenchmark/payment/infrastructure/PaymentSqlQueryRepository.java:21) |
| PR3-04 | forceTransition Arbitrary State/Merchant Change | matched | forceTransition 高风险方法缺失测试，未覆盖状态机、商户改写与回调失败路径 (src/main/java/com/joltbenchmark/payment/application/PaymentDddApplicationService.java:31) |
| PR3-05 | RestTemplate No Timeout | matched | 用户可控回调地址触发服务端外连 (src/main/java/com/joltbenchmark/payment/application/PaymentDddApplicationService.java:40) |
| PR3-06 | Remote Call Inside Transaction | matched | forceTransition 高风险方法缺失测试，未覆盖状态机、商户改写与回调失败路径 (src/main/java/com/joltbenchmark/payment/application/PaymentDddApplicationService.java:31) |
| PR3-07 | callbackUrl SSRF | matched | DddReviewController 新增三个对外接口完全缺失测试覆盖 (src/main/java/com/joltbenchmark/payment/api/DddReviewController.java:15) |
| PR3-08 | Missing Tests For DDD Application Service | matched | forceTransition 高风险方法缺失测试，未覆盖状态机、商户改写与回调失败路径 (src/main/java/com/joltbenchmark/payment/application/PaymentDddApplicationService.java:31) |
| PR3-09 | Lifecycle Policy Full Table Count/List | matched | 使用 new BigDecimal(String) 不算缺陷，但金额阈值比较与 OR 逻辑可能因 amount 为 null 触发 NPE (src/main/java/com/joltbenchmark/payment/domain/PaymentLifecyclePolicy.java:22) |
| PR3-10 | Lifecycle Policy Hardcoded OR Logic | matched | 使用 new BigDecimal(String) 不算缺陷，但金额阈值比较与 OR 逻辑可能因 amount 为 null 触发 NPE (src/main/java/com/joltbenchmark/payment/domain/PaymentLifecyclePolicy.java:22) |
| PR3-11 | overrideStatus valueOf Input Risk | matched | Map 入参字段缺少显式空值和类型校验 (src/main/java/com/joltbenchmark/payment/domain/PaymentOrder.java:117) |
| PR3-12 | overrideStatus Bypasses State Machine | matched | Map 入参字段缺少显式空值和类型校验 (src/main/java/com/joltbenchmark/payment/domain/PaymentOrder.java:117) |
| PR3-13 | reassignMerchant Breaks Ownership/Aggregate | matched | forceTransition 高风险方法缺失测试，未覆盖状态机、商户改写与回调失败路径 (src/main/java/com/joltbenchmark/payment/application/PaymentDddApplicationService.java:31) |
| PR3-14 | Search SQL Injection | matched | insertSnapshotRow 拼接 SQL 写入数据，存在注入和类型错误风险 (src/main/java/com/joltbenchmark/payment/infrastructure/PaymentSqlQueryRepository.java:39) |
| PR3-15 | Snapshot Insert SQL Injection | matched | insertSnapshotRow 拼接 SQL 写入数据，存在注入和类型错误风险 (src/main/java/com/joltbenchmark/payment/infrastructure/PaymentSqlQueryRepository.java:39) |
| PR3-16 | Search Query Unbounded/No Limit | matched | search 方法通过字符串拼接构造 SQL，存在 SQL 注入与执行计划风险 (src/main/java/com/joltbenchmark/payment/infrastructure/PaymentSqlQueryRepository.java:21) |
| PR3-17 | LIKE Leading Wildcard Index Risk | matched | search 查询无分页与结果上限，可能拉取整张 payment_orders (src/main/java/com/joltbenchmark/payment/infrastructure/PaymentSqlQueryRepository.java:20) |
| PR3-18 | Repository Returns API DTO Layer Pollution | matched | search 方法通过字符串拼接构造 SQL，存在 SQL 注入与执行计划风险 (src/main/java/com/joltbenchmark/payment/infrastructure/PaymentSqlQueryRepository.java:21) |
| PR3-19 | Schema Missing PK/NOT NULL/Index | matched | payment_snapshots 缺少主键、NOT NULL 与索引 (src/main/resources/schema.sql:1) |
| PR3-20 | rebuildSnapshots findAll/N+1 | matched | forceTransition 高风险方法缺失测试，未覆盖状态机、商户改写与回调失败路径 (src/main/java/com/joltbenchmark/payment/application/PaymentDddApplicationService.java:31) |

Invalid false positives:
- Map 入参字段缺少显式空值和类型校验 (coding_agent, src/main/java/com/joltbenchmark/payment/domain/PaymentOrder.java:117)
