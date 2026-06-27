# Performance Agent Java Web 代码规范

适用专家：Performance Agent

适用范围：Java / Spring Web 项目的查询、批处理、IO、外部调用、线程池、序列化、分页、内存和资源效率。

排除范围：安全、领域设计、普通编码风格、测试覆盖、Redis 专属一致性问题。

## 输出要求

每个性能问题必须说明触发场景、规模条件、影响和可执行优化方案。没有具体热点证据时不要输出。

## PERF-QUERY-001 禁止无界查询和全量加载

### 规范说明

列表接口、后台任务和导出流程必须有分页、limit、游标或批处理边界。

### 检查点

- `findAll()`、`select *`、无 where 查询。
- 分页 size 未设置上限。
- 导出接口一次性加载全部数据。
- MyBatis XML 无 limit 或条件可为空。

### 如何检查

1. Semgrep / PMD 查找无界查询。
2. 检查 Controller 分页入参。
3. 检查默认 size 和最大 size。

### 反例

```java
List<Order> orders = orderRepository.findAll();
```

### 正例

```java
Page<Order> orders = orderRepository.findByTenantId(
    tenantId,
    PageRequest.of(page, Math.min(size, 100))
);
```

## PERF-NPLUS1-002 循环内不得执行数据库或远程调用

### 规范说明

循环内数据库、HTTP、RPC、Redis 调用会导致 N+1 和高延迟。

### 检查点

- for/stream/map 中调用 repository、mapper、client、template。
- 每个元素单独查详情。
- 循环内发送 MQ 或写日志大对象。

### 如何检查

1. tree-sitter 找循环和 lambda。
2. 检查方法调用对象名是否为 repository/client/mapper/template。
3. 判断是否可批量查询。

### 反例

```java
for (Long userId : userIds) {
    profiles.add(profileRepository.findByUserId(userId));
}
```

### 正例

```java
Map<Long, Profile> profiles = profileRepository.findByUserIdIn(userIds)
    .stream()
    .collect(Collectors.toMap(Profile::userId, Function.identity()));
```

## PERF-TIMEOUT-003 外部调用必须设置超时和重试上限

### 规范说明

外部依赖调用没有超时会耗尽线程；无上限重试会放大故障。

### 检查点

- RestTemplate、WebClient、Feign、OkHttp 超时配置。
- retry 是否有 maxAttempts。
- 是否有熔断、限流或降级。

### 如何检查

1. 查找新增外部客户端。
2. 检查配置类。
3. 判断是否使用默认无限等待。

### 反例

```java
return restTemplate.postForObject(url, req, Resp.class);
```

### 正例

```java
HttpClient client = HttpClient.newBuilder()
    .connectTimeout(Duration.ofSeconds(2))
    .build();
```

## PERF-MEM-004 大对象和集合必须避免无界内存增长

### 规范说明

大文件、导出、批处理、JSON 序列化、日志输出必须采用流式或分批处理。

### 检查点

- `collect(toList())` 处理大数据。
- `StringBuilder` 拼接大响应。
- 一次性读完整文件。
- 日志输出完整对象列表。

### 如何检查

1. 查找导出、批量、文件、报表路径。
2. 检查集合大小是否可控。
3. 检查是否使用 streaming。

### 反例

```java
byte[] bytes = Files.readAllBytes(path);
return Base64.getEncoder().encodeToString(bytes);
```

### 正例

```java
try (InputStream in = Files.newInputStream(path)) {
    return storageClient.uploadStreaming(in);
}
```

## PERF-THREAD-005 线程池和异步任务必须有边界

### 规范说明

异步任务必须设置线程池大小、队列大小、拒绝策略和上下文传播策略。

### 检查点

- `newCachedThreadPool`
- `CompletableFuture.supplyAsync` 未指定 executor。
- 无界队列。
- 异步任务中丢失 trace/user/tenant 上下文。

### 如何检查

1. 查找 executor、async、CompletableFuture。
2. 检查线程池配置。
3. 检查拒绝策略。

### 反例

```java
CompletableFuture.runAsync(() -> sendMessage(order));
```

### 正例

```java
CompletableFuture.runAsync(
    () -> sendMessage(order),
    notificationExecutor
);
```

## PERF-SERIAL-006 序列化和日志不得放大响应耗时

### 规范说明

接口响应和日志不得序列化巨大对象、双向关联对象或敏感上下文。

### 检查点

- 返回 JPA Entity 而不是 DTO。
- Entity 双向关联导致 JSON 膨胀。
- 日志打印完整 request/response。

### 如何检查

1. 检查 Controller 返回类型。
2. 检查 Jackson 注解和 DTO 映射。
3. 检查新增日志语句。

### 反例

```java
@GetMapping("/orders/{id}")
public OrderEntity detail(@PathVariable Long id) {
    return orderRepository.getReferenceById(id);
}
```

### 正例

```java
@GetMapping("/orders/{id}")
public OrderDetailResponse detail(@PathVariable Long id) {
    return orderQueryService.detail(id);
}
```
