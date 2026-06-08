# Redis Java Standard

## 规范说明
适用于 Spring Data Redis、Jedis、Lettuce 的 Java 代码。

## 检查点
- `opsForValue().set` 应设置 TTL 或使用配置化过期策略。
- `setIfAbsent` 锁必须带唯一 token 和过期时间。
- 删除/扫描大量 key 必须使用 SCAN 分批。

## 如何检查
1. 搜索 `redisTemplate`、`StringRedisTemplate`、`setIfAbsent`、`keys`。
2. 检查 TTL、锁释放和异常路径。
3. 输出替代调用代码。

## 反例
```java
redisTemplate.opsForValue().set(key, value);
```

## 正例
```java
redisTemplate.opsForValue().set(key, value, Duration.ofMinutes(10));
```
