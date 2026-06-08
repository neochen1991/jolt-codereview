# Database Agent Java Web 代码规范

适用专家：Database Agent / 数据库专家

适用范围：Java/Spring 数据库访问层、SQL、JDBC、JdbcTemplate、MyBatis、JPA/Hibernate、事务、锁、索引、分页、schema、Flyway、Liquibase、SQL migration、约束、数据迁移、回滚和线上发布兼容性。

排除范围：普通 Java 语法问题、专项安全漏洞、前端、Redis、依赖 CVE 和普通测试覆盖。

## 输出要求

每个数据库 finding 必须包含表名或 SQL/Mapper/Repository 位置、字段名或查询条件、代码行、风险说明、命中的规则编号，以及建议修改 Java 代码或 SQL。

## DB-SQL-001 SQL 必须参数绑定，禁止拼接业务入参

### 规范说明

所有来自请求、配置、消息或外部系统的变量进入 SQL 时必须使用 PreparedStatement、MyBatis `#{}`、JPA 参数绑定或类型安全查询构造器。

### 检查点

- SQL 字符串是否通过 `+`、`String.format`、模板字符串拼接变量。
- MyBatis 是否使用 `${}` 拼接 where/order/table。
- 动态排序、字段名、表名是否有白名单。

### 如何检查

1. 扫描 Repository、Service、Mapper XML 和 SQL 构造代码。
2. 识别变量来源是否可被用户控制。
3. 检查是否使用参数绑定或白名单。

### 反例

```java
String sql = "select * from payments where user_id = '" + userId + "'";
```

### 正例

```java
PreparedStatement ps = connection.prepareStatement(
    "select id, amount from payments where user_id = ? order by created_at desc limit ?"
);
ps.setString(1, userId);
ps.setInt(2, pageSize);
```

## DB-QUERY-002 查询必须有分页、边界或明确结果上限

### 规范说明

面向接口、任务或批处理的数据库查询不得无边界读取大结果集，必须具备分页、limit、游标、id 范围或批量大小控制。

### 检查点

- `select *` 或 `queryForList` 是否无 limit。
- `while (rs.next())` 是否无限累积到集合或响应对象。
- MyBatis/JPA 是否使用内存分页。
- 业务是否可能按租户、用户、状态读取大量数据。

### 如何检查

1. 比对新增 SQL、Repository 方法和调用方。
2. 检查是否存在 `Pageable`、`limit`、游标或 id range。
3. 判断返回结果是否进入 API 响应或内存集合。

### 反例

```sql
SELECT * FROM payments WHERE user_id = ? ORDER BY created_at DESC;
```

### 正例

```sql
SELECT id, amount, status
FROM payments
WHERE user_id = ?
ORDER BY created_at DESC
LIMIT ?;
```

## DB-IDX-003 高频查询字段必须有合适索引

### 规范说明

新增 where、join、order by、group by 字段必须评估索引，组合索引顺序应匹配等值过滤、范围条件和排序字段。

### 检查点

- Repository / Mapper 新增查询条件。
- migration 是否新增对应索引。
- 组合索引顺序是否匹配查询。
- 低选择性字段是否被错误放在索引前缀。

### 如何检查

1. 比对新增 SQL 查询。
2. 检查 migration 是否新增索引。
3. 判断索引是否覆盖过滤和排序。

### 反例

```sql
SELECT * FROM orders WHERE tenant_id = ? AND status = ? ORDER BY created_at DESC;
```

没有索引。

### 正例

```sql
CREATE INDEX idx_orders_tenant_status_created
ON orders (tenant_id, status, created_at);
```

## DB-MAP-004 数据库查询结果不得使用裸 Map 承载业务字段

### 规范说明

数据库查询结果应映射为明确 DTO、Entity、Projection 或 record，不应长期使用 `Map<String,Object>`、`HashMap` 或弱类型字段承载业务语义。

### 检查点

- `queryForList` 返回 `List<Map<String,Object>>`。
- MyBatis `resultType="map"`。
- Repository 方法返回裸 Map。
- 字段名依赖字符串硬编码且缺少类型校验。

### 如何检查

1. 扫描 Repository、Mapper XML、JdbcTemplate 调用。
2. 检查返回值是否继续进入业务逻辑或 API 响应。
3. 判断是否应改为 DTO/Projection。

### 反例

```java
List<Map<String, Object>> rows = jdbcTemplate.queryForList(sql);
```

### 正例

```java
List<PaymentRow> rows = jdbcTemplate.query(sql, paymentRowMapper, userId);
```

## DB-TX-005 多次数据库写入必须有清晰事务边界

### 规范说明

涉及余额、订单、库存、审计、状态流转等多次数据库写入时，必须明确事务边界、隔离级别、失败回滚和幂等条件。

### 检查点

- Service 连续调用多个 Repository 写操作。
- `@Transactional` 是否缺失、放在 private/self-invocation 方法上或传播属性错误。
- 捕获异常后是否吞掉导致事务不回滚。
- 状态更新是否有条件更新或版本号。

### 如何检查

1. 追踪写库调用链。
2. 检查事务注解位置和异常传播。
3. 检查并发下是否会重复扣减或覆盖状态。

### 反例

```java
paymentRepository.updateStatus(id, "PAID");
auditRepository.insert(record);
```

无事务边界。

### 正例

```java
@Transactional
public void markPaid(PaymentId id) {
    paymentRepository.markPaid(id);
    auditRepository.insertPaidEvent(id);
}
```

## DB-LOCK-006 大表变更和批处理必须避免长时间锁表

### 规范说明

大表加列、改类型、建索引、回填数据和批量更新必须考虑锁表、批量大小、在线 DDL、事务时长和失败续跑。

### 检查点

- 修改字段类型。
- 创建索引未使用 online/concurrently。
- 大批量 update/delete 无 limit 或 id range。
- migration 在单事务中执行长耗时操作。

### 如何检查

1. 识别表规模配置或历史风险表。
2. 检查 DDL 类型。
3. 检查是否分批、可续跑和在线执行。

### 反例

```sql
UPDATE orders SET channel = 'APP' WHERE channel IS NULL;
```

### 正例

```sql
UPDATE orders SET channel = 'APP'
WHERE id >= :startId AND id < :endId AND channel IS NULL;
```

## DB-DDL-007 禁止直接删除列或表

### 规范说明

生产环境不得在普通 MR 中直接 `DROP TABLE` 或 `DROP COLUMN`，必须采用灰度迁移和兼容窗口。

### 检查点

- `DROP TABLE`
- `DROP COLUMN`
- 删除 Liquibase changeSet 中的列。
- Java 代码是否仍引用该字段。

### 如何检查

1. 扫描 migration diff。
2. 搜索字段引用。
3. 检查是否有分阶段迁移说明。

### 反例

```sql
ALTER TABLE orders DROP COLUMN remark;
```

### 正例

```sql
-- phase 1: stop writing remark in application
-- phase 2: after compatibility window
ALTER TABLE orders DROP COLUMN remark;
```

## DB-NOTNULL-008 新增非空列必须有默认值或回填方案

### 规范说明

已有表新增 NOT NULL 列必须提供默认值、回填脚本或分阶段迁移。

### 检查点

- `ADD COLUMN xxx NOT NULL`。
- 是否缺少 default。
- 是否有 backfill。
- 是否会锁表或长事务。

### 如何检查

1. 解析 DDL。
2. 判断表是否可能已有数据。
3. 检查默认值和回填。

### 反例

```sql
ALTER TABLE orders ADD COLUMN channel VARCHAR(32) NOT NULL;
```

### 正例

```sql
ALTER TABLE orders ADD COLUMN channel VARCHAR(32) DEFAULT 'UNKNOWN' NOT NULL;
```

## DB-COMPAT-009 应用代码和 schema 必须双向兼容

### 规范说明

发布期间新旧应用可能同时运行，schema 变更必须兼容双版本应用。

### 检查点

- 新代码依赖新字段，但 migration 是否先发布。
- 删除字段前旧代码是否仍读取。
- 字段重命名是否提供兼容字段。
- Entity、Mapper XML、SQL 查询是否和 migration 顺序一致。

### 如何检查

1. 检查 Java Entity、Mapper、SQL 和 migration。
2. 判断发布顺序。
3. 检查是否 expand-contract。

### 反例

直接把 `user_name` 改成 `nickname`，代码同时切换。

### 正例

先新增 `nickname`，双写双读，迁移完成后再删除旧字段。

## DB-ROLLBACK-010 migration 和批处理必须有回滚或补偿方案

### 规范说明

高风险 DDL、数据迁移和批处理必须说明回滚方案；不可逆变更必须显式标注。

### 检查点

- Liquibase rollback 是否存在。
- Flyway 是否有补偿脚本说明。
- 数据删除是否可恢复。
- 批处理失败是否可续跑。
- 是否备份关键数据。

### 如何检查

1. 检查 migration 文件、批处理任务和发布说明。
2. 查找 rollback/compensation 注释。
3. 对不可逆操作输出 finding。

### 反例

```sql
DELETE FROM orders WHERE status = 'EXPIRED';
```

无备份和回滚说明。

### 正例

```sql
CREATE TABLE orders_expired_backup AS
SELECT * FROM orders WHERE status = 'EXPIRED';
DELETE FROM orders WHERE status = 'EXPIRED';
```
