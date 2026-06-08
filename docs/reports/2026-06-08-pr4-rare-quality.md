# GitHub PR4 Rare Issue Quality Report

- Run: `run_75d88b9a0ef543a3`
- Status: waiting_confirmation
- Recall: 0.9500 (19/20)
- False Positive Rate: 0.0690
- Duplicate Rate: 0.0000
- Meets Target: yes

| ID | Expected Issue | Status | Best Match |
| --- | --- | --- | --- |
| P4-01 | Static HashMap is not thread safe | matched | 静态 HashMap 和 ArrayList 在多请求并发访问下不安全 (low_level_defect_agent, src/main/java/com/joltbenchmark/payment/service/RareIssueAuditService.java:32) |
| P4-02 | Static audit cache lacks TTL/capacity/tenant cleanup | matched | 静态审计缓存没有容量和过期策略，可能缓存大列表 (performance_agent, src/main/java/com/joltbenchmark/payment/service/RareIssueAuditService.java:32) |
| P4-03 | ThreadLocal set without remove | matched | ThreadLocal 上下文未清理或跨线程读取 (coding_agent, src/main/java/com/joltbenchmark/payment/service/RareIssueAuditService.java:77) |
| P4-04 | Static SimpleDateFormat is not thread safe | matched | static SimpleDateFormat 在 Spring 单例服务中会产生并发格式化错误 (coding_agent, src/main/java/com/joltbenchmark/payment/service/RareIssueAuditService.java:35) |
| P4-05 | BigDecimal constructed from double | matched | 金额计算先转 double 再构造 BigDecimal 会产生精度误差 (low_level_defect_agent, src/main/java/com/joltbenchmark/payment/service/RareIssueAuditService.java:69) |
| P4-06 | Idempotency window uses LocalDateTime/system timezone | matched | POST 副作用接口缺少幂等保护 (backend_agent, src/main/java/com/joltbenchmark/payment/service/RareIssueAuditService.java:71) |
| P4-07 | SHA-1 weak signature algorithm | matched | 安全签名比较未使用常量时间算法 (security_agent, src/main/java/com/joltbenchmark/payment/service/RareIssueAuditService.java:60) |
| P4-08 | String.equals timing side channel for signature | matched | 安全签名比较未使用常量时间算法 (security_agent, src/main/java/com/joltbenchmark/payment/service/RareIssueAuditService.java:60) |
| P4-09 | Trusts X-Forwarded-For directly | matched | 客户端可控字段绕过风控 (security_agent, src/main/java/com/joltbenchmark/payment/service/RareIssueAuditService.java:53) |
| P4-10 | Sensitive payment/signature logging | matched | 日志输出支付敏感信息和签名 (security_agent, src/main/java/com/joltbenchmark/payment/service/RareIssueAuditService.java:74) |
| P4-11 | Raw new Thread per request | matched | ThreadLocal 上下文未清理或跨线程读取 (coding_agent, src/main/java/com/joltbenchmark/payment/service/RareIssueAuditService.java:77) |
| P4-12 | Background thread reads request ThreadLocal | matched | ThreadLocal 上下文未清理或跨线程读取 (coding_agent, src/main/java/com/joltbenchmark/payment/service/RareIssueAuditService.java:77) |
| P4-13 | JDBC Connection/Statement/ResultSet leak | matched | JDBC 查询连接未释放且关闭 autoCommit 后未恢复 (database_agent, src/main/java/com/joltbenchmark/payment/infrastructure/RareAuditJdbcGateway.java:24) |
| P4-14 | autoCommit false not restored/committed/rolled back | matched | 手动获取 JDBC 连接写库会绕过 Spring 事务边界 (database_agent, src/main/java/com/joltbenchmark/payment/infrastructure/RareAuditJdbcGateway.java:40) |
| P4-15 | JDBC write swallows all exceptions | matched | 交易流水写入绕过 Spring 事务连接 (backend_agent, src/main/java/com/joltbenchmark/payment/infrastructure/RareAuditJdbcGateway.java:40) |
| P4-16 | Mutable object used as HashMap key | matched | 静态 HashMap 和 ArrayList 在多请求并发访问下不安全 (low_level_defect_agent, src/main/java/com/joltbenchmark/payment/service/RareIssueAuditService.java:32) |
| P4-17 | lastErrors returns internal mutable list | matched | Method returns an internal mutable collection directly; return an immutable copy (coding_agent, src/main/java/com/joltbenchmark/payment/service/RareIssueAuditService.java:119) |
| P4-18 | Debug endpoint exposes internal state | missing | - |
| P4-19 | bulkAdjust has no request size limit | matched | bulk-adjust 接口接收无上限 List，请求体和批处理规模不可控 (performance_agent, src/main/java/com/joltbenchmark/payment/api/RareIssueAuditController.java:39) |
| P4-20 | Transactional self invocation | matched | A @Transactional method is invoked through this/self inside the same class; Spri (backend_agent, src/main/java/com/joltbenchmark/payment/service/RareIssueAuditService.java:61) |
