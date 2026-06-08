# Test Agent Java Web 代码规范

适用专家：Test Agent

适用范围：Java / Spring Web 项目的单元测试、集成测试、契约测试、JaCoCo 覆盖率、回归测试、边界场景和断言质量。

排除范围：实现方案、安全漏洞、性能优化、领域建模和 Redis 设计本身。

## 输出要求

测试 finding 必须说明缺失的具体场景、应补的测试类型、建议测试代码。不得泛泛输出“建议补测试”。

## TEST-COVER-001 新增业务分支必须有覆盖

### 规范说明

新增 if/else、状态分支、错误路径、权限路径、支付/订单/账户路径必须有测试覆盖或明确已有覆盖证据。

### 检查点

- diff 新增业务分支。
- JaCoCo 显示新增行未覆盖。
- 未新增对应 `*Test` 或 `*IT`。

### 如何检查

1. 读取 JaCoCo external report。
2. 匹配新增/修改行覆盖率。
3. 检查测试文件 diff。

### 反例

```java
if (request.isForceCancel()) {
    order.forceCancel();
}
```

没有任何 forceCancel 场景测试。

### 正例

```java
@Test
void shouldForceCancelOrderWhenRequestFlagEnabled() {
    // arrange
    // act
    // assert status, event, audit log
}
```

## TEST-ASSERT-002 测试必须有明确断言

### 规范说明

测试不能只调用方法或只验证不报错，必须断言状态、返回值、持久化、副作用或事件。

### 检查点

- 测试方法无 `assert`、`verify`、`then`。
- 只调用 service 方法。
- 断言过于宽泛，如 notNull 但未检查关键字段。

### 如何检查

1. tree-sitter 查找测试方法。
2. 检查 assert/verify 调用。
3. 判断断言是否覆盖关键业务结果。

### 反例

```java
@Test
void createOrder() {
    orderService.create(request);
}
```

### 正例

```java
@Test
void createOrder() {
    Order order = orderService.create(request);
    assertThat(order.status()).isEqualTo(OrderStatus.CREATED);
    assertThat(order.items()).hasSize(2);
}
```

## TEST-BOUND-003 边界值和错误路径必须覆盖

### 规范说明

入参校验、空值、非法枚举、重复请求、并发、回滚、外部依赖失败必须覆盖关键错误路径。

### 检查点

- DTO 新增校验但无 invalid case。
- 异常分支无测试。
- 幂等或并发逻辑无重复请求测试。

### 如何检查

1. 检查新增校验规则和异常分支。
2. 查找测试是否覆盖非法输入。
3. 检查 mock 是否模拟外部失败。

### 反例

只测试正常支付成功，不测试重复支付和支付失败。

### 正例

```java
@Test
void shouldNotCreateDuplicatePaymentWhenCallbackRepeated() {
    paymentCallbackHandler.handle(callback);
    paymentCallbackHandler.handle(callback);
    verify(paymentRepository, times(1)).markPaid(callback.tradeNo());
}
```

## TEST-SLICE-004 Spring 测试类型必须匹配风险

### 规范说明

Controller、Repository、Service、外部集成应使用合适的测试切片，避免过重或过轻。

### 检查点

- Controller 只用纯单测，未验证 JSON、校验和 status code。
- Repository 查询未用 `@DataJpaTest` 或 mapper 测试。
- 关键事务未用集成测试。

### 如何检查

1. 按变更文件判断测试类型。
2. 检查测试注解。
3. 判断是否覆盖框架行为。

### 反例

```java
new OrderController(orderService).create(req);
```

未验证参数校验和 HTTP 状态。

### 正例

```java
@WebMvcTest(OrderController.class)
class OrderControllerTest {
    @Test
    void shouldRejectInvalidRequest() throws Exception {
        mockMvc.perform(post("/orders").content("{}"))
            .andExpect(status().isBadRequest());
    }
}
```

## TEST-REG-005 Bug 修复必须新增回归测试

### 规范说明

修复缺陷时必须新增能复现原问题的测试，防止回归。

### 检查点

- MR 标题或描述包含 fix/bug/regression。
- 修改异常、边界、状态判断。
- 没有新增对应失败用例。

### 如何检查

1. 读取 MR 标题和 diff。
2. 判断是否修复缺陷。
3. 检查测试是否覆盖旧 bug 场景。

### 反例

修复空指针但只加了判空，没有测试空输入。

### 正例

```java
@Test
void shouldReturnEmptyWhenBuyerMissing() {
    Order order = new Order(null);
    assertThat(orderViewMapper.toBuyerName(order)).isEmpty();
}
```

## TEST-CONTRACT-006 对外 API 变更必须有契约测试

### 规范说明

对外接口字段、状态码、枚举、错误码变更必须有契约测试或 OpenAPI diff 证明。

### 检查点

- DTO 字段变更。
- Controller 返回状态码变更。
- OpenAPI diff breaking change。

### 如何检查

1. 读取 OpenAPI diff。
2. 检查 MockMvc / contract test。
3. 判断调用方兼容性。

### 反例

删除响应字段但无契约测试。

### 正例

```java
mockMvc.perform(get("/orders/{id}", id))
    .andExpect(jsonPath("$.id").exists())
    .andExpect(jsonPath("$.status").value("CREATED"));
```
