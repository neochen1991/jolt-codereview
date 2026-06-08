# Spring Backend Agent Java Web 代码规范

适用专家：Spring Backend Agent

适用范围：Java / Spring Web 后端接口、Controller、Service、事务、异常、幂等、接口契约、后台任务和集成调用。

排除范围：安全漏洞由 Security Agent 负责；领域建模由 DDD Agent 负责；性能专项由 Performance Agent 负责；测试覆盖由 Test Agent 负责。

## 输出要求

每个问题必须包含精确位置、触发规则、业务影响、建议修改代码。不要输出单纯格式、命名或个人偏好的意见。

## BE-API-001 Controller 入参必须校验

### 规范说明

所有新增对外接口必须校验必填字段、长度、范围、枚举、日期和嵌套对象。

### 检查点

- `@RequestBody` 是否配合 `@Valid`。
- DTO 字段是否有 `@NotNull`、`@Size`、`@Min`、`@Pattern` 等约束。
- path/query 参数是否校验范围和格式。
- 是否直接信任客户端传入状态、金额、用户 ID。

### 如何检查

1. tree-sitter 提取 Controller 方法和参数注解。
2. 定位 DTO 类。
3. 检查 Bean Validation 约束。
4. 检查 Service 是否做二次业务校验。

### 反例

```java
@PostMapping("/orders")
public Order create(@RequestBody CreateOrderRequest request) {
    return orderService.create(request);
}
```

### 正例

```java
@PostMapping("/orders")
public Order create(@Valid @RequestBody CreateOrderRequest request) {
    return orderService.create(request);
}
```

## BE-TX-002 状态变更必须有明确事务边界

### 规范说明

涉及多次数据库写入、库存、余额、订单状态、审计日志的业务操作必须明确事务边界。

### 检查点

- Service 方法是否包含多次 repository save/update/delete。
- 是否缺少 `@Transactional`。
- 是否在事务内执行慢外部调用。
- 是否存在 self-invocation 导致事务不生效。

### 如何检查

1. 检查 Service 层新增写操作。
2. 检查类级或方法级 `@Transactional`。
3. 若同类内部方法调用被标注事务，检查是否 self-invocation。
4. 检查事务内是否调用 HTTP、MQ、Redis 长耗时操作。

### 反例

```java
public void pay(Long orderId) {
    orderRepository.markPaid(orderId);
    accountRepository.debit(orderId);
}
```

### 正例

```java
@Transactional
public void pay(Long orderId) {
    orderRepository.markPaid(orderId);
    accountRepository.debit(orderId);
}
```

## BE-ERR-003 异常处理必须保留语义并避免误报成功

### 规范说明

异常处理必须明确失败语义，不得吞掉异常、返回成功、丢失关键上下文或把内部异常直接暴露给客户端。

### 检查点

- `catch (Exception)` 后只打印日志或空处理。
- 捕获异常后继续返回成功。
- 错误码与业务语义不匹配。
- 对外响应包含堆栈、SQL、内部类名。

### 如何检查

1. 查找新增 catch 块。
2. 判断 catch 后是否抛出业务异常、返回错误或补偿。
3. 检查日志是否包含必要上下文。
4. 检查返回值是否误导调用方。

### 反例

```java
try {
    paymentClient.pay(req);
} catch (Exception e) {
    log.error("pay failed", e);
}
return PayResult.success();
```

### 正例

```java
try {
    paymentClient.pay(req);
} catch (PaymentException e) {
    log.error("pay failed orderId={}", req.orderId(), e);
    throw new BusinessException("PAYMENT_FAILED");
}
```

## BE-IDEMP-004 写接口必须考虑幂等和重复请求

### 规范说明

支付、订单、发券、审批、消息消费、外部回调等写操作必须处理重复提交和重试。

### 检查点

- 是否有业务唯一键、请求 ID、幂等表或状态机保护。
- 是否存在先查后写但无锁或唯一约束。
- 回调接口是否按外部流水号幂等。
- MQ 消费是否重复执行副作用。

### 如何检查

1. 找到新增写接口或消息消费者。
2. 检查是否使用 requestId、orderNo、eventId。
3. 检查数据库唯一约束或状态条件更新。

### 反例

```java
public void grantCoupon(Long userId, Long couponId) {
    couponRepository.insert(new CouponRecord(userId, couponId));
}
```

### 正例

```java
public void grantCoupon(Long userId, Long couponId, String requestId) {
    if (idempotencyRepository.exists(requestId)) {
        return;
    }
    couponRepository.insertOnce(userId, couponId, requestId);
}
```

## BE-CONTRACT-005 API 兼容性变更必须显式说明

### 规范说明

对外 API 不得无提示删除字段、重命名字段、改变枚举含义、改变状态码或收紧必填约束。

### 检查点

- DTO 删除字段或字段类型变更。
- 枚举新增/删除/语义变化。
- 返回结构从对象改数组或相反。
- HTTP status code 改变。
- OpenAPI diff 命中 breaking change。

### 如何检查

1. 对比 DTO 和 OpenAPI diff。
2. 检查是否有版本化接口或兼容字段。
3. 检查调用方是否同步修改。

### 反例

```java
public record UserResponse(Long id, String nickname) {}
```

原接口曾返回 `name`，本次直接删除。

### 正例

```java
public record UserResponse(Long id, String name, String nickname) {}
```

## BE-INTEGRATION-006 外部调用必须有超时、错误映射和降级

### 规范说明

HTTP、RPC、MQ、第三方 SDK 调用必须设置超时、重试上限、错误映射和降级策略。

### 检查点

- RestTemplate/WebClient/Feign 是否设置 connect/read timeout。
- 重试是否有最大次数和退避。
- 是否把第三方异常映射成业务错误。
- 是否在事务内做慢外部调用。

### 如何检查

1. 查找新增外部客户端调用。
2. 检查 client 配置。
3. 检查异常处理和降级。

### 反例

```java
String body = restTemplate.getForObject(url, String.class);
```

### 正例

```java
ExternalResult result = externalClient.query(req)
    .orTimeout(Duration.ofSeconds(2))
    .onFailureMap(ExternalServiceException::new);
```
