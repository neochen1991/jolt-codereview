# Performance Rule Document Binding Review Quality Report

- MR: mr_repo_github_performance_rule_doc_eval_9501
- Review Run: run_112004785b03424c
- Run Status: waiting_confirmation
- Bound Document: 性能专家规范文档绑定评估 (rule_doc_performance_binding_eval, eval-v1)
- Bound Agent: performance_agent
- Parsed Rule Headings In Document: 6
- Expected Issues: 6
- Final Findings: 6
- Strict Matched Issues: 6
- Strict Missing Issues: 0
- Strict False Positive Findings: 0
- Strict Recall: 100.0%
- Strict False Positive Rate: 0.0%
- Rule-Level Recall: 100.0%
- Performance Agent Findings: 6
- Custom Rule Coverage By Performance Agent: 100.0%
- Meets Target: yes

## Expected Rule Coverage

| Rule | Status | File | Line | Title |
| --- | --- | --- | ---: | --- |
| PERFDOC-QUERY-201 | matched | src/main/java/com/acme/performance/PerformanceOrderQueryService.java | 29 | 查询缺少分页或结果上限 |
| PERFDOC-LIKE-202 | matched | src/main/java/com/acme/performance/PerformanceOrderQueryService.java | 34 | LIKE 前导通配符导致索引失效 |
| PERFDOC-REDIS-203 | matched | src/main/java/com/acme/performance/PerformanceOrderQueryService.java | 39 | 生产路径使用 Redis KEYS |
| PERFDOC-CACHE-204 | matched | src/main/java/com/acme/performance/PerformanceOrderQueryService.java | 49 | 缓存写入缺少 TTL |
| PERFDOC-LOOP-205 | matched | src/main/java/com/acme/performance/PerformanceOrderQueryService.java | 56 | 循环内远程调用 |
| PERFDOC-MEM-206 | matched | src/main/java/com/acme/performance/PerformanceOrderQueryService.java | 63 | 无界结果集一次性进入内存 |

## Final Findings

| Rule(s) | Severity | Confidence | Agent | File | Line | Title |
| --- | --- | ---: | --- | --- | ---: | --- |
| REDIS-TTL-002, PERFDOC-CACHE-204 | medium | 0.86 | performance_agent | src/main/java/com/acme/performance/PerformanceOrderQueryService.java | 49 | 缓存写入缺少 TTL |
| REDIS-CMD-003, PERFDOC-REDIS-203 | high | 0.91 | performance_agent | src/main/java/com/acme/performance/PerformanceOrderQueryService.java | 39 | 生产路径使用 Redis KEYS |
| PERF-QUERY-001, PERF-LIKE-002, PERFDOC-LIKE-202, PERFDOC-QUERY-201 | high | 0.88 | performance_agent | src/main/java/com/acme/performance/PerformanceOrderQueryService.java | 34 | 查询缺少分页且可能无限增长 |
| PERF-QUERY-001, PERFDOC-QUERY-201 | high | 0.86 | performance_agent | src/main/java/com/acme/performance/PerformanceOrderQueryService.java | 28 | 查询缺少分页或结果上限 |
| PERF-MEM-004, PERFDOC-MEM-206 | high | 0.8 | performance_agent | src/main/java/com/acme/performance/PerformanceOrderQueryService.java | 63 | 无界结果集一次性进入内存 |
| PERFDOC-LOOP-205 | high | 0.8 | performance_agent | src/main/java/com/acme/performance/PerformanceOrderQueryService.java | 56 | 循环内远程调用 |

## Missing Rules

None.

## Strict False Positives

None.

## Budget And Agents

- Agents Executed: performance_agent
- LLM Calls: 2
- Tool Calls: 23
- Wall Seconds: 95.842
- Truncated Reason: none
