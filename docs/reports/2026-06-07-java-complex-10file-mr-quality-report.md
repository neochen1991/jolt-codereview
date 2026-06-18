# Java Complex 10-File MR Review Quality Report

- MR: mr_repo_github_java_complex_10file_9301
- Review Run: run_aa8c4d1f2a1f43ce
- Run Status: waiting_confirmation
- Expected Issues: 10
- Final Findings: 9
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
- Evidence Contract Complete: yes
- Evidence Contract Avg Score: 100.0%
- Evidence Contract Risk: ok

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

| Rule(s) | Severity | Confidence | Agent | File | Line | Title | Tool Count | Evidence Contract |
| --- | --- | ---: | --- | --- | ---: | --- | ---: | --- |
| DDD-VO-002, CODE-NULL-001 | medium | 0.92 | ddd_agent | src/main/java/com/acme/payment/domain/PaymentAggregate.java | 7 | 领域模型使用弱类型 Map 表达业务属性 | 2 | satisfied:100.0% |
| REDIS-TTL-002 | medium | 0.92 | redis_agent | src/main/java/com/acme/payment/infra/RedisPaymentCache.java | 23 | Redis 缓存写入缺少 TTL | 4 | satisfied:100.0% |
| PERF-QUERY-001 | medium | 0.89 | performance_agent | src/main/java/com/acme/payment/service/PaymentQueryService.java | 25 | 查询缺少分页或结果上限 | 4 | satisfied:100.0% |
| SEC-SECRET-004 | medium | 0.765 | security_agent | src/main/resources/application-prod.yml | 7 | 配置或代码中包含明文密钥 | 3 | satisfied:100.0% |
| DEP-CVE-001 | medium | 0.765 | dependency_agent | pom.xml | 18 | 依赖组件存在已知漏洞 | 9 | satisfied:100.0% |
| SEC-INJECT-003 | high | 0.9800000000000001 | security_agent | src/main/java/com/acme/payment/service/PaymentQueryService.java | 25 | SQL 使用字符串拼接存在注入风险 | 5 | satisfied:100.0% |
| REDIS-CMD-003 | high | 0.9400000000000001 | redis_agent | src/main/java/com/acme/payment/infra/RedisPaymentCache.java | 16 | 生产路径使用 Redis KEYS 命令 | 3 | satisfied:100.0% |
| CODE-NULL-001, BE-API-001, BE-IDEMP-004 | high | 0.93 | coding_agent | src/main/java/com/acme/payment/api/PaymentAdminController.java | 23 | POST 副作用接口缺少幂等保护 | 7 | satisfied:100.0% |
| DB-DDL-001 | critical | 0.93 | database_agent | src/main/resources/db/migration/V20260607__complex_payment.sql | 2 | 迁移脚本包含破坏性 DDL | 3 | satisfied:100.0% |

## Missing Rules

None.

## False Positive Candidates

None.

## Tool Coverage

| Tool | Calls | Completed | Skipped | Failed | Hits | Rules Hit | Files Hit | Duration ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| git.prepare_source_worktree | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 2989 |
| github.fetch_file_contents | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 5136 |
| github.list_changed_files | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| static.bandit | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 130 |
| static.checkstyle | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 732 |
| static.dependency-check | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 868 |
| static.eslint | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 145 |
| static.gitleaks | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 28 |
| static.java_web_static | 1 | 1 | 0 | 0 | 12 | 12 | 7 | 0 |
| static.kics | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 44 |
| static.openapi-diff | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 183 |
| static.oss_prescan | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 89242 |
| static.osv-scanner | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 57943 |
| static.pmd | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 1518 |
| static.ruff | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 14 |
| static.semgrep | 4 | 4 | 0 | 0 | 11 | 10 | 6 | 13922 |
| static.semgrep.aggregate | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| static.spotbugs | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 277 |
| static.tree_sitter_code_graph | 1 | 1 | 0 | 0 | 5 | 5 | 4 | 4 |
| static.trivy | 1 | 1 | 0 | 0 | 51 | 50 | 1 | 5481 |

## Budget And Agents

- Agents Executed: backend_agent, coding_agent, database_agent, ddd_agent, dependency_agent, frontend_agent, performance_agent, redis_agent, security_agent, test_agent
- LLM Calls: 0
- Tool Calls: 23
- Wall Seconds: 89.619
- Truncated Reason: none
