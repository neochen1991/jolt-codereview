# General Coding Agent Java Web 代码规范

适用专家：General Coding Agent

适用范围：Java 通用实现正确性、空值、边界条件、异常、资源释放、状态一致性、类型使用和可维护性。

排除范围：安全、性能、DDD、Redis、测试覆盖、前端体验和数据库专项。

## 输出要求

只输出会导致真实 bug、错误行为或明显维护风险的问题。每个 finding 必须附带精确行号和建议代码。

## CODE-NULL-001 空值和 Optional 必须显式处理

### 规范说明

可能为空的返回值、请求字段、外部响应、Repository 查询结果必须显式处理，不得隐式解包。

### 检查点

- `findById(...).get()`
- `map.get(key).toString()`
- 外部响应直接链式调用。
- `Optional.orElse(null)` 后未判空。

### 如何检查

1. 检查新增链式调用。
2. 检查 Repository、Map、JSON、外部 client 返回值。
3. 使用 SpotBugs、Error Prone、NullAway 候选证据。

### 反例

```java
Order order = orderRepository.findById(id).get();
return order.getBuyer().getName();
```

### 正例

```java
Order order = orderRepository.findById(id)
    .orElseThrow(() -> new BusinessException("ORDER_NOT_FOUND"));
return Optional.ofNullable(order.getBuyer())
    .map(Buyer::getName)
    .orElse("");
```

## CODE-BOUND-002 集合、分页和索引必须处理边界

### 规范说明

集合读取、分页参数、批量大小、字符串截取必须处理空集合、越界和非法参数。

### 检查点

- `list.get(0)` 前是否判空。
- page/size 是否有限制。
- substring 下标是否可能越界。
- 批量操作是否处理空列表。

### 如何检查

1. 检查新增集合访问和字符串截取。
2. 检查分页 DTO 是否有默认值和最大值。
3. 检查空列表调用 SQL in 条件。

### 反例

```java
Long firstId = ids.get(0);
```

### 正例

```java
if (ids == null || ids.isEmpty()) {
    return Collections.emptyList();
}
Long firstId = ids.get(0);
```

## CODE-EXC-003 异常捕获范围必须精确

### 规范说明

不得无差别捕获 `Exception` 或 `Throwable`，除非处于统一入口并有明确错误映射。

### 检查点

- `catch (Exception e)` 是否掩盖不同失败原因。
- `catch (Throwable t)` 是否吞掉 Error。
- 是否丢失上下文或重复包装。

### 如何检查

1. 查找 catch 块。
2. 判断是否可以捕获更具体异常。
3. 检查日志和重新抛出语义。

### 反例

```java
try {
    mapper.readValue(json, User.class);
} catch (Exception e) {
    return null;
}
```

### 正例

```java
try {
    return mapper.readValue(json, User.class);
} catch (JsonProcessingException e) {
    throw new BusinessException("INVALID_USER_JSON", e);
}
```

## CODE-STATE-004 状态更新必须保持一致

### 规范说明

多字段状态变更必须保证前后一致，不得只更新部分字段或留下不可达状态。

### 检查点

- 状态枚举切换是否遗漏关联时间、操作人、版本。
- 失败分支是否回滚内存对象或数据库状态。
- 是否存在重复分支或死代码。

### 如何检查

1. 找到状态字段赋值。
2. 检查状态机条件和关联字段。
3. 检查是否有并发版本保护。

### 反例

```java
order.setStatus(OrderStatus.PAID);
orderRepository.save(order);
```

遗漏 `paidAt` 和 `paidBy`。

### 正例

```java
order.markPaid(currentUserId, clock.now());
orderRepository.save(order);
```

## CODE-RESOURCE-005 资源必须正确关闭

### 规范说明

IO、Stream、Connection、ResultSet、InputStream、Response 必须明确关闭或使用框架托管。

### 检查点

- 是否使用 try-with-resources。
- 是否返回未关闭流。
- 是否在异常路径泄漏资源。

### 如何检查

1. SpotBugs 资源泄漏候选。
2. 查找 `new FileInputStream`、`connection.prepareStatement`。
3. 检查 close 语义。

### 反例

```java
InputStream in = new FileInputStream(file);
return parser.parse(in);
```

### 正例

```java
try (InputStream in = new FileInputStream(file)) {
    return parser.parse(in);
}
```

## CODE-CONFIG-006 配置读取必须有默认值和失败处理

### 规范说明

新增配置必须明确默认值、取值范围和缺失时行为。

### 检查点

- `@Value("${x}")` 无默认值。
- 配置值直接 parse，未处理非法值。
- feature flag 缺少默认关闭策略。

### 如何检查

1. 查找 `@Value`、`@ConfigurationProperties`。
2. 检查校验注解和默认值。
3. 检查非法配置启动失败或降级行为。

### 反例

```java
@Value("${payment.retry-count}")
private int retryCount;
```

### 正例

```java
@Validated
@ConfigurationProperties(prefix = "payment")
public record PaymentProperties(
    @Min(0) @Max(5) int retryCount
) {}
```
