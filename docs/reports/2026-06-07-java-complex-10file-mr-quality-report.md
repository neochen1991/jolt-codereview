# Java Complex 10-File MR Review Quality Report

- MR: mr_repo_github_java_complex_10file_9301
- Review Run: run_fe3253527e594601
- Run Status: waiting_confirmation
- Expected Issues: 10
- Final Findings: 8
- Strict Matched Issues: 9
- Strict Missing Issues: 1
- Strict False Positive Findings: 0
- Strict Recall: 90.0%
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
| BE-API-001 | missing | src/main/java/com/acme/payment/api/PaymentAdminController.java | 22 | 接口 RequestBody 缺少 @Valid |
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
| CODE-NULL-001, BE-API-001, TEST-ASSERT-002, TEST-BOUND-003, TEST-SLICE-004 | medium | 0.99 | coding_agent | src/main/java/com/acme/payment/api/PaymentAdminController.java | 23 | Map 入参字段缺少显式空值和类型校验 | 6 | satisfied:100.0% |
| REDIS-TTL-002, SEC-CONFIG-007, TEST-ASSERT-002 | medium | 0.98 | security_agent | src/main/java/com/acme/payment/infra/RedisPaymentCache.java | 23 | Redis缓存写入未设置TTL可能造成内存泄漏 | 4 | satisfied:100.0% |
| CODE-STATE-004, DDD-VO-002 | medium | 0.9700000000000001 | coding_agent | src/main/java/com/acme/payment/domain/PaymentAggregate.java | 14 | markPaid 方法缺少 paidAt 时间戳和 paidBy 操作人字段 | 2 | satisfied:100.0% |
| DEP-CVE-001 | medium | 0.9700000000000001 | security_agent | pom.xml | 20 | 引入存在反序列化漏洞的Fastjson 1.2.47依赖 | 9 | satisfied:100.0% |
| CODE-RESOURCE-005, BE-INTEGRATION-006, DB-SQL-001, PERF-QUERY-001, SEC-INJECT-003, TEST-ASSERT-002, TEST-BOUND-003, TEST-REG-005 | high | 0.99 | performance_agent | src/main/java/com/acme/payment/service/PaymentQueryService.java | 22 | SQL 拼接存在 SQL 注入风险，恶意 userId 可导致数据库资源耗尽 | 5 | satisfied:100.0% |
| REDIS-CMD-003, CODE-BOUND-002, REDIS-DEGRADE-006, TEST-ASSERT-002, TEST-BOUND-003 | high | 0.99 | security_agent | src/main/java/com/acme/payment/infra/RedisPaymentCache.java | 16 | Redis KEYS命令在生产环境存在性能与安全风险 | 3 | satisfied:100.0% |
| SEC-SECRET-004, CODE-CONFIG-006 | high | 0.9500000000000001 | security_agent | src/main/resources/application-prod.yml | 7 | 生产配置硬编码数据库明文密码 | 3 | satisfied:100.0% |
| DB-DDL-001 | high | 0.9500000000000001 | database_agent | src/main/resources/db/migration/V20260607__complex_payment.sql | 2 | 迁移脚本包含破坏性 DDL | 3 | satisfied:100.0% |

## Missing Rules
- BE-API-001

## False Positive Candidates

None.

## Tool Coverage

| Tool | Calls | Completed | Skipped | Failed | Hits | Rules Hit | Files Hit | Duration ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| deepagents.inspect_agent_rules | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| deepagents.inspect_diff_summary | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| deepagents.inspect_static_observations | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| deepagents.list_skill_assets | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| deepagents.read_diff_patch | 7 | 7 | 0 | 0 | 0 | 0 | 0 | 0 |
| deepagents.read_skill_asset | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| git.prepare_source_worktree | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 6207 |
| github.fetch_file_contents | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 7630 |
| github.list_changed_files | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| static.bandit | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 156 |
| static.checkstyle | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 858 |
| static.dependency-check | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 955 |
| static.eslint | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 203 |
| static.gitleaks | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 34 |
| static.java_web_static | 1 | 1 | 0 | 0 | 9 | 9 | 7 | 0 |
| static.kics | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 49 |
| static.openapi-diff | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 226 |
| static.oss_prescan | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 86004 |
| static.osv-scanner | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 48807 |
| static.pmd | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 1972 |
| static.ruff | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 15 |
| static.semgrep | 4 | 4 | 0 | 0 | 11 | 10 | 6 | 18176 |
| static.semgrep.aggregate | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| static.spotbugs | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 331 |
| static.tree_sitter_code_graph | 1 | 1 | 0 | 0 | 4 | 4 | 4 | 4 |
| static.trivy | 1 | 1 | 0 | 0 | 51 | 50 | 1 | 4974 |

## Budget And Agents

- Agents Executed: backend_agent, coding_agent, database_agent, ddd_agent, dependency_agent, low_level_defect_agent, performance_agent, redis_agent, security_agent, test_agent
- LLM Calls: 14
- Tool Calls: 36
- Wall Seconds: 1003.521
- Truncated Reason: none
