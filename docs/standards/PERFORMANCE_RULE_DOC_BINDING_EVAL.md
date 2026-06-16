# 性能专家规范文档绑定评估

适用专家：性能 Agent

适用范围：Java / Spring 业务代码中的数据库访问、缓存、Redis、循环远程调用和内存占用风险。

排除范围：低级空指针、金额精度、安全漏洞、DDD 建模、依赖 CVE、前端交互。

## PERFDOC-QUERY-201 查询缺少分页或结果上限
- severity: high
- category: performance_unbounded_query
- applies_to: src/main/java/**/*.java

### 规范说明
新增查询不得在接口或服务热路径中执行无分页、无 limit、无游标边界的全量查询；必须设置 page size、limit 或业务上限。

### 检查点
- 是否出现 `statement.executeQuery(sql)` 且 SQL 没有 `limit`、分页或游标条件。
- 查询结果是否可能随租户、用户或时间范围无限增长。
- 是否在接口同步链路中读取全量结果。

### 证据要求
必须展示 SQL 构造行、执行查询行和缺少分页或 limit 的说明。

### 反例
`ResultSet rs = statement.executeQuery(sql);`

### 正例
`PreparedStatement ps = connection.prepareStatement(sql + " limit ?");`

### 误报模式
SQL 使用唯一键等值查询并且数据库约束保证最多一条结果。

### 修复建议
增加分页、limit、游标或业务时间窗口，并补充大数据量回归测试。

## PERFDOC-LIKE-202 LIKE 前导通配符导致索引失效
- severity: medium
- category: performance_like_index
- applies_to: src/main/java/**/*.java

### 规范说明
新增 SQL 不得使用 `LIKE '%keyword%'` 这类前导通配查询扫描大表；应使用前缀查询、倒排索引或搜索服务。

### 检查点
- SQL 是否拼接或绑定了 `like '%`。
- 查询字段是否是订单号、姓名、备注等高基数字段。
- 是否缺少分页和搜索降级策略。

### 证据要求
必须展示 LIKE 条件行和可能导致索引失效的说明。

### 反例
`String sql = "select * from payment_orders where remark like '%" + keyword + "%'";`

### 正例
`String sql = "select * from payment_orders where remark like ? limit ?";`

### 误报模式
字段使用专门全文索引，或查询只作用于极小的临时表。

### 修复建议
改成前缀查询、全文索引、搜索服务，或者加受控分页与熔断。

## PERFDOC-REDIS-203 生产路径使用 Redis KEYS
- severity: high
- category: performance_redis_blocking
- applies_to: src/main/java/**/*.java

### 规范说明
生产请求路径不得使用 Redis `KEYS` 扫描 keyspace；该命令会阻塞 Redis 主线程，应使用 SCAN 或维护业务索引。

### 检查点
- 是否出现 `redisTemplate.keys("order:*")`。
- 是否位于 Controller、Service 或定时任务热路径。
- 是否有批量上限、SCAN 游标或异步治理。

### 证据要求
必须展示 KEYS 调用行和调用所在业务路径。

### 反例
`Set<String> keys = redisTemplate.keys("payment:*");`

### 正例
`Cursor<byte[]> cursor = connection.scan(ScanOptions.scanOptions().match("payment:*").count(500).build());`

### 误报模式
仅在本地测试工具或一次性离线脚本中使用。

### 修复建议
使用 SCAN 分批处理，或维护业务索引集合并限制单次处理量。

## PERFDOC-CACHE-204 缓存写入缺少 TTL
- severity: medium
- category: performance_cache_lifecycle
- applies_to: src/main/java/**/*.java

### 规范说明
新增缓存写入必须设置 TTL、容量或清理策略；热路径永久缓存会造成内存持续膨胀和陈旧数据。

### 检查点
- 是否出现 `redisTemplate.opsForValue().set(cacheKey, response)` 且没有 Duration/timeout。
- cache key 是否包含用户、订单或搜索条件导致 key 数量持续增长。
- 是否存在主动清理或容量控制。

### 证据要求
必须展示缓存 set 行和缺少 TTL 的说明。

### 反例
`redisTemplate.opsForValue().set(cacheKey, response);`

### 正例
`redisTemplate.opsForValue().set(cacheKey, response, Duration.ofMinutes(10));`

### 误报模式
该 key 是少量固定配置并且有明确外部生命周期管理。

### 修复建议
设置合理 TTL，或说明永久 key 的容量、清理和一致性策略。

## PERFDOC-LOOP-205 循环内远程调用
- severity: high
- category: performance_loop_remote_call
- applies_to: src/main/java/**/*.java

### 规范说明
新增代码不得在订单、用户、商品等集合循环内逐条调用远程服务；会产生 N+1 网络调用、放大延迟并耗尽线程池。

### 检查点
- 是否在 `for` 循环内调用 `riskClient.fetchRiskScore(order.getId())`。
- 是否可以改为批量接口、并发受控调用或异步预取。
- 是否缺少超时、限流和降级策略。

### 证据要求
必须展示循环声明行和循环体内远程调用行。

### 反例
`RiskScore score = riskClient.fetchRiskScore(order.getId());`

### 正例
`Map<Long, RiskScore> scores = riskClient.batchFetchRiskScores(orderIds);`

### 误报模式
集合大小由上游强约束为极小固定值，且有明确并发隔离。

### 修复建议
改为批量接口、缓存预取或受控并发，并设置超时和降级。

## PERFDOC-MEM-206 无界结果集一次性进入内存
- severity: high
- category: performance_memory_pressure
- applies_to: src/main/java/**/*.java

### 规范说明
新增导出、报表或聚合逻辑不得把无界结果集一次性 `findAll` 后 `collect(Collectors.toList())` 进入内存；应使用分页、流式游标或批处理。

### 检查点
- 是否出现 `orderRepository.findAll()`。
- 是否紧接着 `collect(Collectors.toList())` 或一次性构造大字符串。
- 是否缺少分页、流式处理和内存上限。

### 证据要求
必须展示全量读取行和一次性收集/拼接行。

### 反例
`List<Order> orders = orderRepository.findAll().stream().collect(Collectors.toList());`

### 正例
`orderRepository.streamAll(batchSize, consumer);`

### 误报模式
表是固定小规模字典表，且有数据库约束或启动期加载证明。

### 修复建议
使用分页、游标或流式写出，避免请求线程持有完整结果集。
