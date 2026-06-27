# Performance Core Standard

## 规范说明
只报告会明显影响吞吐、延迟、容量、资源占用或稳定性的性能问题。

## 检查点
- 热路径是否存在 N+1 IO、全表扫描、无界循环或阻塞调用。
- 是否缺少超时、批量、分页、缓存失效或资源释放。
- 是否把大对象、完整响应或无限集合放入内存/缓存。

## 如何检查
1. 识别同步入口和循环。
2. 追踪每次循环中的 DB/HTTP/Redis/文件 IO。
3. 判断是否在请求热路径且有规模放大风险。

## 反例
```java
for (Long id : ids) repository.findById(id);
```

## 正例
```java
Map<Long, Order> orders = repository.findAllById(ids).stream().collect(toMap(Order::id, identity()));
```
