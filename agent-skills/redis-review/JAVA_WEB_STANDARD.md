# Redis Agent Java Web 代码规范

适用专家：Redis Agent

适用范围：Java / Spring 项目中的 Redis、Spring Cache、Redisson、分布式锁、缓存一致性、TTL、key 设计、Redis 队列和危险命令。

排除范围：普通性能问题、安全漏洞、领域建模、测试覆盖和数据库专项。

## 输出要求

每个 Redis finding 必须说明 key、命令、TTL、一致性影响和建议修改代码。

## REDIS-KEY-001 key 必须包含业务隔离维度

### 规范说明

缓存 key 必须包含租户、项目、用户或业务归属维度，避免跨租户、跨项目串数据。

### 检查点

- key 是否只包含简单 ID。
- 多租户系统是否包含 tenantId。
- key 前缀是否稳定、可读、可迁移。

### 如何检查

1. 查找 `RedisTemplate`、`StringRedisTemplate`、`@Cacheable`。
2. 检查 key 表达式。
3. 结合项目多租户配置判断隔离字段。

### 反例

```java
String key = "order:" + orderId;
```

### 正例

```java
String key = "tenant:" + tenantId + ":order:" + orderId;
```

## REDIS-TTL-002 缓存写入必须设置 TTL

### 规范说明

除非明确为永久业务 key，否则缓存写入必须设置 TTL 和清理策略。

### 检查点

- `opsForValue().set(key, value)` 是否缺 TTL。
- `@Cacheable` 是否有 cache 配置 TTL。
- hash/list/set 是否有过期策略。

### 如何检查

1. 查找 Redis 写入。
2. 检查是否调用 `expire`、`set` 带 timeout、`setIfAbsent` 带 timeout。
3. 检查配置中心是否定义 TTL。

### 反例

```java
redisTemplate.opsForValue().set(key, payload);
```

### 正例

```java
redisTemplate.opsForValue().set(key, payload, Duration.ofMinutes(30));
```

## REDIS-CMD-003 禁止生产热路径使用 KEYS 等危险命令

### 规范说明

生产热路径不得使用 `KEYS`、无界 `LRANGE`、无界 `SMEMBERS`、大批量 `DEL`。

### 检查点

- `keys(pattern)`。
- `range(key, 0, -1)`。
- 全量 set/list/zset 读取。
- 批量删除无分片、无 scan。

### 如何检查

1. 静态扫描 Redis 危险命令。
2. 判断是否位于启动脚本、离线任务还是接口热路径。
3. 热路径命中必须输出。

### 反例

```java
Set<String> keys = redisTemplate.keys("order:*");
redisTemplate.delete(keys);
```

### 正例

```java
ScanOptions options = ScanOptions.scanOptions()
    .match("order:*")
    .count(500)
    .build();
```

## REDIS-LOCK-004 分布式锁必须有唯一 token 和过期时间

### 规范说明

分布式锁必须具备过期时间、唯一持有者 token、安全释放和异常释放逻辑。

### 检查点

- `setIfAbsent` 是否带 TTL。
- 解锁是否校验 token。
- 是否在 finally 中释放。
- Redisson lock 是否设置 lease time 或看门狗策略明确。

### 如何检查

1. 查找 lock、setIfAbsent、RLock。
2. 检查 TTL 和 token。
3. 检查释放逻辑。

### 反例

```java
redisTemplate.opsForValue().setIfAbsent(lockKey, "1");
// business
redisTemplate.delete(lockKey);
```

### 正例

```java
String token = UUID.randomUUID().toString();
Boolean locked = redisTemplate.opsForValue()
    .setIfAbsent(lockKey, token, Duration.ofSeconds(30));
try {
    if (Boolean.TRUE.equals(locked)) {
        doBusiness();
    }
} finally {
    redisLock.release(lockKey, token);
}
```

## REDIS-CONSIST-005 缓存更新必须说明一致性策略

### 规范说明

数据库与缓存双写必须明确采用删除缓存、延迟双删、消息失效、版本号或最终一致性策略。

### 检查点

- 更新 DB 后是否更新或删除缓存。
- 是否先写缓存再写 DB。
- 是否处理事务失败和消息失败。
- 是否有版本号防止旧值覆盖新值。

### 如何检查

1. 找到 DB 写操作和缓存写/删操作。
2. 检查顺序和事务边界。
3. 检查失败补偿。

### 反例

```java
orderRepository.save(order);
redisTemplate.opsForValue().set(orderKey, order);
```

### 正例

```java
orderRepository.save(order);
transactionSynchronization.afterCommit(() -> cacheInvalidator.delete(orderKey));
```

## REDIS-DEGRADE-006 Redis 异常必须有降级路径

### 规范说明

缓存失败不能扩大成核心业务失败，除非 Redis 本身就是强一致业务存储。

### 检查点

- 查询接口 Redis 读取失败是否回源 DB。
- 写缓存失败是否影响主交易。
- 是否区分缓存异常和业务异常。

### 如何检查

1. 检查 Redis 调用是否包裹降级。
2. 判断该 Redis 是缓存还是业务状态。
3. 缓存场景异常直接抛出则输出 finding。

### 反例

```java
Order order = (Order) redisTemplate.opsForValue().get(key);
return order;
```

### 正例

```java
try {
    Order cached = cacheClient.get(key);
    if (cached != null) return cached;
} catch (RedisConnectionFailureException e) {
    log.warn("redis unavailable key={}", key, e);
}
return orderRepository.findById(orderId).orElseThrow();
```
