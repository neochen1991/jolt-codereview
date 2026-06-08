# Java Complex 10-File MR Review Quality Report

- MR: mr_repo_github_java_complex_10file_9301
- Review Run: run_c8f4d54826c14f55
- Run Status: waiting_confirmation
- Expected Issues: 10
- Final Findings: 10
- Strict Matched Issues: 10
- Strict Missing Issues: 0
- Strict False Positive Findings: 0
- Strict Recall: 100.0%
- Strict False Positive Rate: 0.0%
- Rule-Level Matched Issues: 10
- Rule-Level Recall: 100.0%
- Meets Target: yes
- Trace Complete: yes
- Suggested Code Complete: yes

## Expected Issue Coverage

| Rule | Status | File | Line | Title |
| --- | --- | --- | ---: | --- |
| BE-API-001 | matched | src/main/java/com/acme/payment/api/PaymentAdminController.java | 22 | 接口 RequestBody 缺少 @Valid |
| CODE-NULL-001 | matched | src/main/java/com/acme/payment/api/PaymentAdminController.java | 23 | String.valueOf 可能把缺失字段转成字符串 null |
| SEC-INJECT-003 | matched | src/main/java/com/acme/payment/service/PaymentQueryService.java | 22 | SQL 使用字符串拼接存在注入风险 |
| PERF-QUERY-001 | matched | src/main/java/com/acme/payment/service/PaymentQueryService.java | 22 | 查询缺少分页或 limit 容易产生大结果集 |
| REDIS-CMD-003 | matched | src/main/java/com/acme/payment/infra/RedisPaymentCache.java | 16 | 生产路径使用 Redis KEYS 命令 |
| REDIS-TTL-002 | matched | src/main/java/com/acme/payment/infra/RedisPaymentCache.java | 23 | Redis 缓存写入缺少 TTL |
| DDD-VO-002 | matched | src/main/java/com/acme/payment/domain/PaymentAggregate.java | 12 | 聚合根使用 Map<String,Object> 表达领域属性 |
| SEC-SECRET-004 | matched | src/main/resources/application-prod.yml | 7 | 生产配置包含明文数据库密码 |
| DB-DDL-001 | matched | src/main/resources/db/migration/V20260607__complex_payment.sql | 2 | 迁移脚本直接 DROP COLUMN 存在兼容风险 |
| DEP-CVE-001 | matched | pom.xml | 17 | fastjson 1.2.47 存在已知高危漏洞 |

## Final Findings

| Rule(s) | Severity | Confidence | Agent | File | Line | Title | Tool Count |
| --- | --- | ---: | --- | --- | ---: | --- | ---: |
| REDIS-TTL-002 | medium | 0.92 | redis_agent | src/main/java/com/acme/payment/infra/RedisPaymentCache.java | 23 | 缓存写入未设置 TTL | 2 |
| DDD-VO-002 | medium | 0.88 | ddd_agent | src/main/java/com/acme/payment/domain/PaymentAggregate.java | 12 | 领域模型使用弱类型 Map 表达业务属性 | 2 |
| PERF-QUERY-001 | medium | 0.8 | performance_agent | src/main/java/com/acme/payment/service/PaymentQueryService.java | 22 | 查询缺少分页或结果上限 | 2 |
| DEP-CVE-001 | medium | 0.8 | dependency_agent | pom.xml | - | 依赖组件存在已知漏洞 | 9 |
| CODE-NULL-001, LLDEF-NULL-001, LOW_LEVEL_DEFECT-001 | high | 0.93 | low_level_defect_agent | src/main/java/com/acme/payment/api/PaymentAdminController.java | 23 | Map payload 使用 String.valueOf 会把缺失字段转成字面量 "null" | 2 |
| DB-DDL-001, DB-COMPAT-005, DB-ROLLBACK-006 | high | 0.92 | database_agent | src/main/resources/db/migration/V20260607__complex_payment.sql | 2 | 直接 DROP COLUMN legacy_channel 破坏发布兼容窗口 | 2 |
| REDIS-CMD-003 | high | 0.9 | redis_agent | src/main/java/com/acme/payment/infra/RedisPaymentCache.java | 16 | 禁止在生产路径使用 KEYS + 批量 DELETE | 2 |
| BE-API-001 | high | 0.9 | backend_agent | src/main/java/com/acme/payment/api/PaymentAdminController.java | 22 | POST /admin/payments/search 接收裸 Map 入参且未使用 @Valid，缺少入参校验 | 2 |
| SEC-SECRET-004 | high | 0.86 | security_agent | src/main/resources/application-prod.yml | 7 | 配置或代码中包含明文密钥 | 2 |
| SEC-INJECT-003 | high | 0.86 | security_agent | src/main/java/com/acme/payment/service/PaymentQueryService.java | 25 | SQL 使用字符串拼接存在注入风险 | 2 |

## Missing Rules

None.

## False Positive Candidates

None.

## Tool Coverage

| Tool | Calls | Completed | Skipped | Failed | Hits | Rules Hit | Files Hit | Duration ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| deepagents.inspect_agent_rules | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| deepagents.inspect_diff_summary | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| deepagents.inspect_static_observations | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| deepagents.list_skill_assets | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| deepagents.read_skill_asset | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| github.list_changed_files | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| static.bandit | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 199 |
| static.checkstyle | 1 | 1 | 0 | 0 | 70 | 5 | 7 | 833 |
| static.dependency-check | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 936 |
| static.eslint | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 214 |
| static.gitleaks | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 38 |
| static.java_web_static | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| static.kics | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 58 |
| static.openapi-diff | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 296 |
| static.oss_prescan | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 68384 |
| static.osv-scanner | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 31565 |
| static.pmd | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 1720 |
| static.ruff | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 24 |
| static.semgrep | 1 | 1 | 0 | 0 | 9 | 9 | 6 | 23724 |
| static.spotbugs | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 337 |
| static.trivy | 1 | 1 | 0 | 0 | 51 | 50 | 1 | 3786 |

## Budget And Agents

- Agents Executed: backend_agent, coding_agent, context_builder, database_agent, ddd_agent, debate_moderator, dependency_agent, low_level_defect_agent, orchestrator, performance_agent, redis_agent, router_agent, security_agent, summary_agent, test_agent, verifier
- LLM Calls: 9
- Tool Calls: 22
- Wall Seconds: 460.982
- Truncated Reason: none
