# DDD Design Agent Java Web 代码规范

适用专家：DDD Design Agent

适用范围：Java / Spring 项目中的领域模型、聚合边界、实体、值对象、领域服务、应用服务、仓储、领域事件和 bounded context。

排除范围：普通空值 bug、安全漏洞、性能细节、Redis 命令、测试覆盖和前端问题。

## 输出要求

DDD finding 必须说明业务语义影响，不能只说“设计不优雅”。必须给出可落地重构建议和示例代码。

## DDD-AGG-001 聚合必须维护自身不变量

### 规范说明

订单、账户、库存、审批、合同等核心业务状态的不变量必须由聚合方法维护，不能散落在 Controller、Application Service 或脚本中。

### 检查点

- Controller 或 Service 是否直接 set 多个领域字段。
- 是否绕过聚合方法修改状态。
- 不变量是否只靠调用方记住顺序。

### 如何检查

1. 查找 `setStatus`、`setAmount`、`setXxx` 等状态修改。
2. 判断是否位于领域对象外部。
3. 检查聚合是否有表达业务意图的方法。

### 反例

```java
order.setStatus(OrderStatus.PAID);
order.setPaidAt(now);
order.setPaidAmount(amount);
```

### 正例

```java
order.markPaid(amount, now);
```

## DDD-VO-002 关键业务概念必须建模为值对象

### 规范说明

金额、手机号、邮箱、订单号、租户 ID、权限码、时间范围等关键概念不应长期使用裸 `String`、`Long`、`BigDecimal`。

### 检查点

- 方法参数是否存在多个相同基础类型且语义不同。
- 校验逻辑是否散落在多个调用方。
- 值对象是否封装格式、范围和比较逻辑。

### 如何检查

1. 查找核心领域方法的基础类型参数。
2. 检查是否重复校验同一业务概念。
3. 判断是否适合提炼值对象。

### 反例

```java
public void transfer(Long fromAccountId, Long toAccountId, BigDecimal amount) {}
```

### 正例

```java
public void transfer(AccountId from, AccountId to, Money amount) {}
```

## DDD-APP-003 应用服务只编排流程

### 规范说明

Application Service 负责用例编排、事务和外部协作，不应承载复杂业务规则。

### 检查点

- Service 方法是否包含大量 if/else 业务规则。
- 是否直接计算领域状态。
- 是否操作多个实体字段来维护不变量。

### 如何检查

1. 找到 `*ApplicationService`、`*Service`。
2. 判断规则是否属于领域概念。
3. 若规则可由聚合或领域服务表达，输出 finding。

### 反例

```java
if (order.getStatus() == CREATED && payment.isSuccess()) {
    order.setStatus(PAID);
}
```

### 正例

```java
order.confirmPayment(payment);
```

## DDD-REPO-004 仓储接口必须面向聚合和业务查询

### 规范说明

领域层仓储不应泄露 ORM 细节、分页实现、SQL 片段或基础设施对象。

### 检查点

- Repository 方法是否暴露 `EntityManager`、`QueryWrapper`、SQL 字符串。
- 是否返回基础设施 PO。
- 是否按聚合根查询和保存。

### 如何检查

1. 检查 repository interface 所在包。
2. 检查方法签名是否泄露技术细节。
3. 检查返回类型是否为领域对象或业务视图。

### 反例

```java
List<OrderEntity> query(QueryWrapper<OrderEntity> wrapper);
```

### 正例

```java
Optional<Order> find(OrderId orderId);
List<OrderSummary> findPendingOrders(TenantId tenantId);
```

## DDD-CTX-005 不同上下文模型不得互相复用

### 规范说明

不同 bounded context 的模型不能为了省事直接复用，否则会产生语义污染和耦合。

### 检查点

- payment 模块是否直接依赖 order domain entity。
- user DTO 是否被多个上下文作为领域对象使用。
- 是否缺少 anti-corruption layer。

### 如何检查

1. 用 import 图检查跨 context 依赖。
2. 判断被复用类型是否具有上下文语义。
3. 检查是否存在转换器或 ACL。

### 反例

```java
import com.acme.order.domain.Order;

public class InvoiceService {
    public Invoice create(Order order) {}
}
```

### 正例

```java
public Invoice create(OrderSnapshot snapshot) {}
```

## DDD-EVENT-006 领域事件必须表达已发生事实

### 规范说明

领域事件命名和内容必须表达已经发生的业务事实，并明确发布时机。

### 检查点

- 事件是否命名为命令式：`PayOrderEvent`。
- 是否在事务提交前发送外部消息。
- 事件是否携带过多实体对象。

### 如何检查

1. 查找 `Event`、`publish`、MQ send。
2. 检查事件命名和字段。
3. 检查事务提交后发布机制。

### 反例

```java
eventPublisher.publish(new PayOrderEvent(order));
```

### 正例

```java
domainEvents.add(new OrderPaidEvent(order.id(), order.paidAt()));
```
