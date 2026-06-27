# Redis Core Standard

## 规范说明
只报告 Redis key、TTL、一致性、锁、Lua、pipeline、队列和热点风险。

## 检查点
- 写入缓存是否设置 TTL 或明确永不过期理由。
- 是否使用 `KEYS`、大 key、热 key 或无界 scan。
- 分布式锁是否有 token、过期和释放校验。

## 如何检查
1. 定位 RedisTemplate/Jedis/Lettuce 调用。
2. 追踪 key 组成、TTL 和删除策略。
3. 检查缓存与数据库更新顺序。

## 反例
```java
redisTemplate.keys("order:*").forEach(redisTemplate::delete);
```

## 正例
```java
scanAndDelete("order:", batchSize);
```
