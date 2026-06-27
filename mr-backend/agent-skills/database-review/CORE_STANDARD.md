# Database Core Standard

## 规范说明
只报告数据库相关风险，包括 SQL、schema、索引、事务、锁、ORM/Mapper、数据迁移、回滚、发布兼容性和数据一致性。

## 检查点
- 查询是否缺少分页、索引、排序边界或结果上限。
- Repository/Mapper/ORM 映射是否使用弱类型、字段不匹配或 N+1 查询。
- 事务边界、锁粒度、批处理和回滚补偿是否明确。
- DDL、NOT NULL、DROP/RENAME、唯一约束和数据回填是否支持灰度发布。
- 数据库连接、ResultSet、Statement 是否正确释放。

## 如何检查
1. 读取 Java、XML Mapper、SQL、Flyway/Liquibase、配置和 migration diff。
2. 关联新增 SQL 与表字段、索引、事务、实体映射和发布顺序。
3. 对每个问题给出可执行的 SQL 或 Java 修改建议。

## 反例
```java
String sql = "select * from payments where user_id = '" + userId + "'";
```

## 正例
```java
PreparedStatement ps = connection.prepareStatement(
    "select id, amount from payments where user_id = ? order by created_at desc limit ?"
);
```
