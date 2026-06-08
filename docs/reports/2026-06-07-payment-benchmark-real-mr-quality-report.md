# Payment Benchmark Real MR Quality Report

- MR: `mr_repo_3a83959a2dc948d6_3818935246`
- Run: `run_34cf8bf164e948b3`
- Status: `waiting_confirmation`
- Summary: 输出 27 个问题
- Expected Issues: 17
- Final Findings: 27
- Matched Issues: 17
- Missing Issues: 0
- False Positive Findings: 1
- Duplicate Valid Findings: 13
- Recall: 1.0000
- False Positive Rate: 0.0370
- Meets Target: yes
- LLM Calls: 18
- Tool Calls: 32
- Truncated Reason: none

## Issue Coverage

| # | Expected Issue | Status | Best Match |
| ---: | --- | --- | --- |
| 1 | Unauthenticated Admin Balance Adjustment | matched | 管理员余额调整接口缺少认证、授权与归属校验 (src/main/java/com/joltbenchmark/payment/api/AccountController.java:36) |
| 2 | Unsafe Negative and Arbitrary Balance Changes | matched | adjustBalance 未对入参 amount 与 currency 做空值与货币一致性校验 (src/main/java/com/joltbenchmark/payment/service/AccountService.java:44) |
| 3 | Sensitive Card Data Accepted and Stored | matched | PaymentOrder 实体新增字段缺失 schema migration 与发布兼容方案 (src/main/java/com/joltbenchmark/payment/domain/PaymentOrder.java:24) |
| 4 | Sensitive Card Data Returned in API Responses | matched | 配置或代码中包含明文密钥 (src/main/java/com/joltbenchmark/payment/api/dto/PaymentResponse.java:8) |
| 5 | Sensitive Data Logged | matched | 配置或代码中包含明文密钥 (src/main/java/com/joltbenchmark/payment/service/PaymentService.java:76) |
| 6 | Risk-Control Bypass Flag | matched | 客户端可控字段绕过风控 (src/main/java/com/joltbenchmark/payment/service/PaymentService.java:90) |
| 7 | Localhost IP Risk Bypass | matched | 客户端可控字段绕过风控 (src/main/java/com/joltbenchmark/payment/service/PaymentService.java:90) |
| 8 | Money Precision Loss | matched | MoneyNormalizer 通过 double 中转破坏金额精度 (src/main/java/com/joltbenchmark/payment/service/MoneyNormalizer.java:10) |
| 9 | Refund Allowed After Already Refunded | matched | 退款状态机允许对已退款订单再次退款 (src/main/java/com/joltbenchmark/payment/service/RefundService.java:43) |
| 10 | Refund Amount Not Compared to Paid Amount or Prior Refunds | matched | 退款状态机允许对已退款订单再次退款 (src/main/java/com/joltbenchmark/payment/service/RefundService.java:43) |
| 11 | Weak Webhook Signature Trust | matched | Webhook 签名校验不可信 (src/main/java/com/joltbenchmark/payment/service/WebhookService.java:30) |
| 12 | Loose Webhook Event Matching | matched | Webhook 签名校验不可信 (src/main/java/com/joltbenchmark/payment/service/WebhookService.java:30) |
| 13 | Untrusted Callback URL Invocation | matched | PaymentOrder 实体新增字段缺失 schema migration 与发布兼容方案 (src/main/java/com/joltbenchmark/payment/domain/PaymentOrder.java:24) |
| 14 | Debug Endpoints Expose Internal Data | matched | 调试接口未鉴权且泄露全量支付数据 (src/main/java/com/joltbenchmark/payment/api/BenchmarkDebugController.java:15) |
| 15 | Stack Trace Leakage | matched | Server error config includes stack traces; disable stack traces in client respon (src/main/resources/application.yml:22) |
| 16 | SQL Logging Enabled in Application Config | matched | 生产配置暴露敏感运行时信息 (src/main/resources/application.yml:13) |
| 17 | Test Configuration Masks Missing Coverage | matched | Test configuration skips high-risk path tests; do not mask callback, auth, debug (src/test/resources/application-test.yml:24) |

## False Positive Findings

- Refund logic allows already-refunded payments; enforce refund state machine and  (coding_agent, src/main/java/com/joltbenchmark/payment/domain/PaymentOrder.java:137)

## Duplicate Valid Findings

- webhook 事件类型匹配过于宽松且未判空 (coding_agent, src/main/java/com/joltbenchmark/payment/service/WebhookService.java:32)
- 退款状态判断散落在应用服务，PaymentOrder 聚合未维护可退款不变量 (ddd_agent, src/main/java/com/joltbenchmark/payment/service/RefundService.java:43)
- listPayments 对 customerId 访问未判空 (coding_agent, src/main/java/com/joltbenchmark/payment/api/BenchmarkDebugController.java:30)
- 金额、币种、商户、操作人等关键概念长期使用裸 String/BigDecimal (ddd_agent, src/main/java/com/joltbenchmark/payment/service/AccountService.java:44)
- 管理员余额调整 DTO 关键字段缺少校验 (backend_agent, src/main/java/com/joltbenchmark/payment/api/dto/AdminBalanceAdjustmentRequest.java:7)
- ConfirmPaymentRequest 新增 skipRiskCheck 字段未做后端业务校验 (backend_agent, src/main/java/com/joltbenchmark/payment/api/dto/ConfirmPaymentRequest.java:5)
- listPayments 接口无分页无上限，全表加载并在内存过滤 (database_agent, src/main/java/com/joltbenchmark/payment/api/BenchmarkDebugController.java:29)
- 用户可控回调地址触发服务端外连 (security_agent, src/main/java/com/joltbenchmark/payment/service/NotificationService.java:20)
- adjustBalance 余额读改写缺少事务边界与乐观锁，存在并发覆盖与部分失败风险 (database_agent, src/main/java/com/joltbenchmark/payment/service/AccountService.java:44)
- adjustBalance 多次写库未声明事务边界 (backend_agent, src/main/java/com/joltbenchmark/payment/service/AccountService.java:44)
- RestTemplate 未配置连接和读取超时，回调可能耗尽 Tomcat 线程 (performance_agent, src/main/java/com/joltbenchmark/payment/service/NotificationService.java:13)
- listPayments 中对 customerId getter 结果直接调用 contains，存在 NPE 风险 (low_level_defect_agent, src/main/java/com/joltbenchmark/payment/api/BenchmarkDebugController.java:30)
- 商户回调使用默认 RestTemplate 未配置超时与重试上限 (backend_agent, src/main/java/com/joltbenchmark/payment/service/NotificationService.java:12)
