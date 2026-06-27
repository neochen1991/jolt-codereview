# Database Java Standard

## 规范说明
适用于 Java/Spring 项目的数据库访问、事务、ORM/Mapper、SQL 和 Flyway/Liquibase migration。

## 检查点
- Controller/Service/Repository 是否绕过事务边界直接执行数据库写入。
- JDBC/MyBatis/JPA 查询是否参数绑定、分页、索引友好。
- Entity/DTO/Mapper 字段是否和 schema 兼容。
- `db/migration` 版本号不可重复，不可修改已发布 migration。
- DDL 与应用读写路径需支持双写/双读窗口。

## 如何检查
1. 检查 Java Repository/Mapper、XML mapper、`@Transactional`、`V*.sql` 和 changelog diff。
2. 查找 SQL 拼接、无界查询、弱类型 Map 结果、N+1、DROP、RENAME、NOT NULL、唯一约束。
3. 给出分阶段 migration、索引、参数绑定或事务边界修改代码。

## 反例
```java
List<Map<String, Object>> rows = jdbcTemplate.queryForList(sql);
```

## 正例
```java
List<PaymentRow> rows = jdbcTemplate.query(sql, rowMapper, userId, pageSize);
```
