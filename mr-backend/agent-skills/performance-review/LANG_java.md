# Performance Java Standard

## 规范说明
适用于 Java / Spring 服务性能检视，聚焦数据库、Redis、HTTP 客户端、线程池和事务边界。

## 检查点
- Repository/Mapper 调用是否在循环内。
- `RestTemplate/WebClient/HttpClient` 是否设置连接和读取超时。
- `@Transactional` 内是否包含远程 IO 或长循环。

## 如何检查
1. 搜索新增 `for/stream/while` 和 IO 调用。
2. 检查查询是否批量化、分页化。
3. 检查超时、连接池、限流和回压配置。

## 反例
```java
ids.forEach(id -> restTemplate.getForObject(url + id, DTO.class));
```

## 正例
```java
List<DTO> result = client.batchQuery(ids, timeout);
```
