# DDD Design Agent Java Web 代码规范

适用专家：DDD Design Agent

适用范围：Java / Spring 项目中的战略设计、限界上下文、领域模型、聚合边界、实体、值对象、领域服务、应用服务、仓储、领域事件、分层依赖、CQRS、演进兼容和多租户隔离。

排除范围：普通空值 bug、安全漏洞、性能微优化、Redis 命令细节、测试覆盖和前端问题。若同一代码同时包含 DDD 设计风险和实现缺陷，DDD Agent 只输出领域语义、模型边界、规则表达和一致性方面的问题。

## 输出要求

DDD finding 必须说明业务语义影响，不能只说“设计不优雅”。每个 finding 必须落在当前 MR diff 的精确新增行，必须说明违反的 DDD 规则、业务后果、误报边界和可落地重构建议。

不要仅因 Controller、Service 或 Repository 中出现 `@Autowired` 字段注入就输出 DDD 问题；只有当领域对象、值对象或 domain 包直接依赖 Spring Bean、Repository、Redis、HTTP 等基础设施，且造成领域模型污染时才可报告。

## 战略设计

## DDD-CTX-001 限界上下文边界必须清晰

### 规范说明
核心业务能力应按限界上下文组织包、模块和模型，不能把支付、订单、会员、风控、清结算等语义混在同一领域对象里。
### 检查点
- 新增包名、类名是否混合多个上下文语义。
- 一个 service 是否同时修改多个上下文模型。
- 是否出现万能 `CommonDomain`、`BusinessModel`、`BaseOrder`。
### 如何检查
查看 package/import/类名/方法名是否跨上下文；确认每个模型是否只有单一业务语言。
### 反例
```java
paymentOrder.applyUserCoupon(orderAddress, riskScore);
```
### 正例
```java
paymentContext.pay(orderSnapshot, couponSnapshot, riskDecision);
```

## DDD-CTX-002 不同上下文不得复用领域实体

### 规范说明
不同 bounded context 之间不能直接传递或持久化对方的领域实体，应使用快照、DTO、ACL 或 Published Language。
### 检查点
- `payment` 直接 import `order.domain.Order`。
- 结算、发票、风控直接依赖交易聚合实体。
- DTO 被当成领域对象长期复用。
### 如何检查
检查 import 图和方法签名，跨上下文实体进入领域方法时输出。
### 反例
```java
public Invoice createInvoice(Order order) {}
```
### 正例
```java
public Invoice createInvoice(OrderBillingSnapshot snapshot) {}
```

## DDD-CTX-003 上下文集成必须有防腐层

### 规范说明
外部系统、旧系统或其他上下文的模型进入本上下文前必须经过 ACL 转换，不能让外部字段和状态语义污染领域模型。
### 检查点
- 外部响应对象直接传给聚合。
- 第三方状态码直接作为领域状态。
- 没有 translator/assembler/adapter。
### 如何检查
查找 `ClientResponse`、`RemoteDto`、`OpenApiDto` 进入 domain/application 方法。
### 反例
```java
payment.applyGatewayResponse(response);
```
### 正例
```java
payment.applyGatewayResult(gatewayTranslator.toDomainResult(response));
```

## DDD-CTX-004 通用语言必须体现在命名中

### 规范说明
类、方法、事件和异常应使用业务语言表达意图，不能长期使用 `process`、`handle`、`type=1`、`flag` 等含混命名承载关键规则。
### 检查点
- 关键业务方法只有技术动作名。
- 状态、类型、原因只用魔法数字或短字符串。
- 业务异常没有业务语义。
### 如何检查
检查新增 public 方法、事件、枚举和异常命名。
### 反例
```java
order.process(1, true);
```
### 正例
```java
order.confirmMerchantSettlement(SettlementPolicy policy);
```

## DDD-CTX-005 模块边界不得被入口层或基础设施绕穿

### 规范说明
Controller、Scheduler、Consumer、Repository 实现不能绕过应用服务直接改领域状态或调用其他上下文仓储。
### 检查点
- Controller 直接访问 Repository。
- Consumer 直接 `setStatus` 后保存。
- Infra 实现调用另一个上下文的 domain service。
### 如何检查
检查入口层和基础设施层新增依赖方向。
### 反例
```java
@PostMapping("/pay")
public void pay(String id) { paymentRepository.find(id).setStatus(PAID); }
```
### 正例
```java
@PostMapping("/pay")
public void pay(PayRequest request) { payApplicationService.pay(request.toCommand()); }
```

## 聚合与事务边界

## DDD-AGG-001 聚合必须维护自身不变量

### 规范说明
订单、账户、库存、审批、合同等核心业务状态的不变量必须由聚合方法维护，不能散落在 Controller、Application Service 或脚本中。
### 检查点
- Controller 或 Service 是否直接 set 多个领域字段。
- 是否绕过聚合方法修改状态。
- 不变量是否只靠调用方记住顺序。
### 如何检查
查找 `setStatus`、`setAmount`、`setMerchantId`、`override`、`force` 等状态修改。
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

## DDD-AGG-002 外部不得直接改写聚合内部状态

### 规范说明
聚合内部字段、集合和子实体只能通过表达业务意图的方法变更，禁止外部任意覆盖归属、终态、金额、余额和生命周期。
### 检查点
- `forceTransition`、`overrideStatus`、`reassignMerchant`。
- public setter 修改核心字段。
- 使用反射、Map、JSON patch 改领域状态。
### 如何检查
检查新增 public 方法是否允许任意状态或归属输入。
### 反例
```java
payment.setMerchantId(newMerchantId);
payment.setStatus(PaymentStatus.valueOf(input));
```
### 正例
```java
payment.transferMerchant(new MerchantId(newMerchantId), policy);
```

## DDD-AGG-003 聚合边界不能过大

### 规范说明
聚合应围绕强一致性不变量设计，不能把查询、历史、明细、报表、审批流和外部快照全部塞进同一个大对象。
### 检查点
- 聚合包含大量 unrelated collection。
- 保存一个聚合会级联更新多张弱相关表。
- 只为查询方便扩大聚合。
### 如何检查
检查新增字段、集合、构造参数和 repository save 范围。
### 反例
```java
class MerchantAggregate { List<Order> orders; List<Invoice> invoices; List<LoginLog> logs; }
```
### 正例
```java
class Merchant { MerchantId id; MerchantStatus status; }
```

## DDD-AGG-004 一个事务内优先只修改一个聚合

### 规范说明
单个本地事务内应优先修改一个聚合；跨聚合一致性需要明确事务脚本、领域事件、Saga/Process Manager 或补偿策略。
### 检查点
- 一个 `@Transactional` 方法保存多个聚合根。
- 跨账户、订单、库存同时强一致写入。
- 没有事件或补偿说明。
### 如何检查
查找一个方法内多个 repository.save 或 mapper.update。
### 反例
```java
orderRepository.save(order);
accountRepository.save(account);
inventoryRepository.save(inventory);
```
### 正例
```java
order.markPaid();
orderRepository.save(order);
domainEventPublisher.publish(new OrderPaidEvent(order.id()));
```

## DDD-AGG-005 跨聚合一致性必须显式建模

### 规范说明
跨聚合协作不能依赖调用顺序和隐式约定，必须有领域事件、流程管理器、幂等键、补偿和失败语义。
### 检查点
- 跨聚合步骤没有事件或流程状态。
- 异常后部分聚合已提交。
- 重试会重复扣减或重复发放。
### 如何检查
检查 application service 中多步写操作和异常处理。
### 反例
```java
payment.pay();
coupon.use();
points.add();
```
### 正例
```java
processManager.handle(new PaymentConfirmedEvent(paymentId));
```

## DDD-AGG-006 聚合根不得暴露可变集合或内部实体引用

### 规范说明
聚合应保护内部子实体和集合，不能返回可变集合让外部绕过不变量。
### 检查点
- getter 返回 `List`、`Map`、数组原引用。
- 外部可直接 add/remove 子实体。
- 集合元素没有业务方法维护。
### 如何检查
查找领域对象 getter 和集合字段。
### 反例
```java
public List<OrderLine> getLines() { return lines; }
```
### 正例
```java
public List<OrderLine> lines() { return List.copyOf(lines); }
```

## DDD-AGG-007 聚合创建必须维护初始不变量

### 规范说明
聚合创建应通过工厂、静态命名构造或构造器校验完成，禁止 `new` 后 set 多个字段拼装半成品。
### 检查点
- `new Aggregate()` 后连续 setter。
- 构造器允许 null/非法状态。
- 初始状态没有业务语义。
### 如何检查
检查新增创建流程和构造器。
### 反例
```java
Payment payment = new Payment();
payment.setStatus(CREATED);
payment.setAmount(amount);
```
### 正例
```java
Payment payment = Payment.create(command.paymentId(), command.money());
```

## DDD-AGG-008 聚合状态流转必须显式建模

### 规范说明
核心生命周期应通过状态机、策略或聚合方法集中表达，不能在多个服务中复制 if/else。
### 检查点
- 多处 `if(status == ...)` 决定下一状态。
- `valueOf(input)` 直接转换终态。
- 无非法流转保护。
### 如何检查
查找状态枚举使用和状态变更入口。
### 反例
```java
if ("PAID".equals(next)) order.setStatus(PAID);
```
### 正例
```java
order.transitionTo(PAID, transitionPolicy);
```

## DDD-AGG-009 聚合方法必须表达业务意图

### 规范说明
聚合 public 方法应描述业务动作，不能只有技术性 `update`、`sync`、`merge`、`patch` 承载复杂规则。
### 检查点
- 方法名无法看出业务语义。
- 一个 `update(Map)` 覆盖多种动作。
- 业务规则隐藏在参数组合中。
### 如何检查
检查聚合新增 public 方法和参数。
### 反例
```java
payment.update(payload);
```
### 正例
```java
payment.confirmCallback(callbackResult);
```

## DDD-AGG-010 聚合不得依赖外部服务完成内部判断

### 规范说明
聚合内部规则应基于传入的值对象、策略或领域服务结果，不应直接调用 RPC、Repository、Redis 或 HTTP。
### 检查点
- domain 对象注入 client/repository/cache。
- 聚合方法调用外部服务。
- 领域判断依赖实时远程查询。
### 如何检查
检查 domain 包 import 和字段依赖。
### 反例
```java
if (riskClient.allowed(userId)) this.status = APPROVED;
```
### 正例
```java
payment.approve(riskDecision);
```

## 实体和值对象

## DDD-ENT-001 实体 identity 必须稳定且语义明确

### 规范说明
实体身份应由业务唯一标识或领域 ID 表达，不能依赖数据库自增 ID、可变字段或组合字符串拼接承担领域身份。
### 检查点
- equals/hashCode 使用可变字段。
- 领域方法只接收裸 `Long id`。
- ID 字符串没有类型区分。
### 如何检查
检查实体 ID、equals/hashCode 和方法参数。
### 反例
```java
boolean same = order.getDbId().equals(other.getDbId());
```
### 正例
```java
boolean same = order.id().equals(other.id());
```

## DDD-ENT-002 实体相等性不能误用全部字段

### 规范说明
实体相等性应基于 identity，不能用 Lombok `@Data` 或全字段 equals 导致状态变化影响集合行为。
### 检查点
- 实体类使用 `@Data`。
- equals/hashCode 包含 status、amount、updatedAt。
- 实体放入 Set/Map 后可变字段变化。
### 如何检查
检查实体注解和 equals/hashCode。
### 反例
```java
@Data
class Payment { private PaymentId id; private PaymentStatus status; }
```
### 正例
```java
@EqualsAndHashCode(of = "id")
class Payment { private final PaymentId id; }
```

## DDD-VO-001 值对象必须不可变

### 规范说明
值对象应不可变、可比较、自校验，不能暴露 setter 或可变集合。
### 检查点
- 值对象字段非 final 且有 setter。
- 构造后仍可改金额、币种、范围。
- 返回内部可变集合。
### 如何检查
检查 `*Id`、`Money`、`DateRange`、`Address` 等类。
### 反例
```java
money.setAmount(new BigDecimal("-1"));
```
### 正例
```java
Money money = Money.of(amount, Currency.CNY);
```

## DDD-VO-002 关键业务概念必须建模为值对象

### 规范说明
金额、手机号、邮箱、订单号、租户 ID、商户 ID、权限码、时间范围等关键概念不应长期使用裸 `String`、`Long`、`BigDecimal`。
### 检查点
- 方法参数存在多个相同基础类型且语义不同。
- 校验逻辑散落在多个调用方。
- 业务概念没有封装格式、范围和比较逻辑。
### 如何检查
查找核心领域方法的基础类型参数和重复校验。
### 反例
```java
public void transfer(Long fromAccountId, Long toAccountId, BigDecimal amount) {}
```
### 正例
```java
public void transfer(AccountId from, AccountId to, Money amount) {}
```

## DDD-VO-003 金额和币种必须一起建模

### 规范说明
金额不能只用 BigDecimal 表示，必须绑定币种、精度、舍入和比较语义。
### 检查点
- amount 和 currency 分散传递。
- BigDecimal 比较/舍入逻辑散落。
- 货币换算没有领域服务或策略。
### 如何检查
检查支付、结算、退款、账务相关方法。
### 反例
```java
refund(BigDecimal amount, String currency);
```
### 正例
```java
refund(Money refundAmount);
```

## DDD-VO-004 值对象不得依赖基础设施

### 规范说明
值对象只能表达业务值和校验，不能依赖 Repository、Spring Bean、HTTP、Redis、数据库或时钟之外的可变基础设施。
### 检查点
- 值对象注入 Bean。
- 值对象查询数据库验证。
- 值对象包含 JPA lazy association。
### 如何检查
检查 value object import 和字段。
### 反例
```java
class MerchantId { @Autowired MerchantRepository repository; }
```
### 正例
```java
record MerchantId(String value) { MerchantId { requireValid(value); } }
```

## DDD-VO-005 Map/JSON/Object 不能替代领域模型

### 规范说明
领域层不能用 `Map<String,Object>`、`JsonNode`、`Object`、通用 `properties` 承载长期业务状态。
### 检查点
- 聚合持有 Map/JSON 扩展字段。
- 业务规则通过字符串 key 读取。
- 缺少值对象和显式字段。
### 如何检查
查找 domain/application 中的弱类型容器。
### 反例
```java
Object status = payload.get("status");
```
### 正例
```java
PaymentStatus status = PaymentStatus.from(payload.status());
```

## DDD-VO-006 时间范围和时区必须显式建模

### 规范说明
账期、有效期、冻结期、预约时间等时间规则必须封装范围、时区、闭开区间和重叠判断。
### 检查点
- start/end 分散传递。
- LocalDateTime 无时区语义。
- 重叠判断多处复制。
### 如何检查
检查结算、订阅、有效期、任务调度代码。
### 反例
```java
activate(LocalDateTime start, LocalDateTime end);
```
### 正例
```java
activate(EffectivePeriod period);
```

## DDD-VO-007 枚举必须表达业务状态和未知值策略

### 规范说明
枚举扩展应考虑持久化兼容、未知值、废弃值和状态流转，不能直接 `valueOf` 用户或外部输入。
### 检查点
- `Enum.valueOf(input)` 进入领域状态。
- 无 UNKNOWN/兼容策略。
- 状态枚举和数据库值无迁移方案。
### 如何检查
检查状态转换和外部输入映射。
### 反例
```java
this.status = PaymentStatus.valueOf(request.status());
```
### 正例
```java
this.status = PaymentStatus.fromExternal(request.status());
```

## 应用服务与领域服务

## DDD-APP-001 应用服务只负责编排

### 规范说明
Application Service 负责用例编排、事务和外部协作，不应承载核心业务规则。
### 检查点
- Service 方法包含大量业务 if/else。
- 直接计算领域状态。
- 操作多个实体字段维护不变量。
### 如何检查
找到 `*ApplicationService`、`*Service`，判断规则是否属于领域概念。
### 反例
```java
if (order.getStatus() == CREATED && payment.isSuccess()) order.setStatus(PAID);
```
### 正例
```java
order.confirmPayment(payment);
```

## DDD-APP-002 应用服务不能直接 set 多个领域字段

### 规范说明
应用服务不应通过多个 setter 维护聚合一致性，应调用聚合方法或领域服务。
### 检查点
- 一个方法内连续 `setXxx`。
- 保存前手工拼状态、金额、时间。
- 调用顺序即业务规则。
### 如何检查
检查 application/service 层新增 setter 调用。
### 反例
```java
payment.setStatus(SUCCESS);
payment.setCallbackTime(now);
payment.setSettledAmount(amount);
```
### 正例
```java
payment.confirmCallback(callbackResult, now);
```

## DDD-APP-003 应用服务事务边界必须清晰

### 规范说明
应用服务写用例应显式表达事务边界，并避免在事务内混入慢外部调用或不可回滚副作用。
### 检查点
- 写方法缺少事务。
- 事务内发 MQ/HTTP/邮件。
- 异常导致领域状态与外部副作用不一致。
### 如何检查
检查 `@Transactional`、外部调用和保存顺序。
### 反例
```java
repository.save(order);
gateway.charge(order);
```
### 正例
```java
repository.save(order);
outbox.add(new OrderCreatedMessage(order.id()));
```

## DDD-APP-004 应用服务不得返回 ORM 实体给接口层

### 规范说明
应用服务对外应返回用例结果或 DTO，不应把 JPA Entity、MyBatis PO 或领域聚合直接暴露给 Controller。
### 检查点
- 返回 `PaymentEntity`、`OrderDO`。
- Controller 序列化领域对象。
- lazy field 泄漏到 API。
### 如何检查
检查 application 方法返回值和 Controller 调用。
### 反例
```java
public PaymentEntity getPayment(String id) { return repository.getReferenceById(id); }
```
### 正例
```java
public PaymentView getPayment(PaymentId id) { return queryService.findView(id); }
```

## DDD-APP-005 应用服务命令对象必须表达用例意图

### 规范说明
应用服务入参应是命令对象或明确值对象，不能直接接收 Web Request、Map 或多个裸基础类型。
### 检查点
- application 方法接收 `HttpServletRequest`、`RequestBody`、Map。
- 入参列表很长且同类型重复。
- 命令对象缺少校验和语义。
### 如何检查
检查 application service public 方法签名。
### 反例
```java
pay(String id, String merchantId, BigDecimal amount, String currency);
```
### 正例
```java
pay(PayCommand command);
```

## DDD-DOM-SVC-001 领域服务只承载跨聚合领域规则

### 规范说明
领域服务用于无法自然归属单个聚合的领域规则，不能成为事务脚本、远程调用编排或工具类。
### 检查点
- domain service 注入多个 repository/client。
- 只有 CRUD 编排没有领域语言。
- 方法名是 `handle/process/sync`。
### 如何检查
检查 domain service 依赖和方法语义。
### 反例
```java
class PaymentDomainService { void process(Payment p) { repository.save(p); } }
```
### 正例
```java
class SettlementPolicy { SettlementDecision decide(Payment payment, Account account) {} }
```

## DDD-DOM-SVC-002 领域服务不得退化成贫血模型脚本容器

### 规范说明
如果所有业务规则都在 service 中操作实体 getter/setter，实体只是数据袋，应迁移行为到聚合或值对象。
### 检查点
- Entity 只有字段和 setter。
- Service 中大量读取字段后判断。
- 领域对象无业务方法。
### 如何检查
对照 service 规则和 entity 方法。
### 反例
```java
if (payment.getAmount().compareTo(limit) > 0) payment.setStatus(REVIEW);
```
### 正例
```java
payment.requireManualReviewIfExceeds(limit);
```

## DDD-POLICY-001 策略对象必须表达业务语义

### 规范说明
复杂可变规则应建模为 Policy、Specification、RuleSet 或 Strategy，不能长期散落硬编码 if/else。
### 检查点
- 同一条件在多处复制。
- 风控、优惠、结算规则硬编码。
- 缺少规则版本和解释。
- Policy、Rule、Strategy 中定义了 `priority`、`order`、`rank`、`effectiveAt`、`version` 等业务决策字段，但选择、排序、冲突解决或审计解释没有使用。
### 如何检查
检查新增复杂条件和重复判断；对策略/规则集合，逐一核对业务字段是否参与最终 `select`、`sort`、`filter`、`decide` 或决策日志。
### 反例
```java
if (amount.compareTo(new BigDecimal("1000")) > 0 && vip) {}

policyRepository.save(new RiskPolicy(expression, priority));
return policyCache.get("active").decide(order);
```
### 正例
```java
RiskPolicy policy = policyRepository.findActive(merchantId).stream()
    .sorted(RiskPolicy::comparePriority)
    .findFirst()
    .orElseThrow();
policy.decide(order);
```

## 仓储与基础设施隔离

## DDD-REPO-001 Repository 面向聚合根

### 规范说明
领域仓储应保存和查询聚合根，不能围绕表、字段、局部子实体或 DAO 细节建模。
### 检查点
- repository 保存子实体绕过聚合。
- 方法名是表字段查询。
- 聚合根和持久化对象混用。
### 如何检查
检查 repository 接口方法和返回类型。
### 反例
```java
orderLineRepository.save(line);
```
### 正例
```java
orderRepository.save(order);
```

## DDD-REPO-002 领域 Repository 不得泄漏 ORM/SQL 细节

### 规范说明
领域层 Repository 接口不得暴露 `EntityManager`、`QueryWrapper`、`Pageable`、SQL 字符串、MyBatis Example 等基础设施类型。
### 检查点
- repository interface 位于 domain 包但入参是 ORM 类型。
- 返回 PO/DO/EntityManager。
- 方法接收 SQL 片段。
### 如何检查
检查 domain repository import 和签名。
### 反例
```java
List<Order> query(QueryWrapper<OrderEntity> wrapper);
```
### 正例
```java
List<OrderSummary> findPendingOrders(TenantId tenantId);
```

## DDD-REPO-003 Repository 不应承载业务决策

### 规范说明
Repository 负责持久化和查询，不应决定状态流转、风控通过、折扣计算或业务策略。
### 检查点
- repository 方法名含 approve/settle/refund decision。
- SQL CASE 表达业务状态。
- 查询结果直接作为规则结论。
### 如何检查
检查 repository 方法名和 SQL 逻辑。
### 反例
```java
boolean canRefund = paymentRepository.canRefund(paymentId);
```
### 正例
```java
payment.canRefund(refundPolicy);
```

## DDD-REPO-004 查询模型与聚合仓储要分离

### 规范说明
复杂列表、报表、分页和统计应使用 query service/read model，不应污染聚合仓储或迫使聚合为查询而变形。
### 检查点
- 聚合仓储返回分页 DTO。
- Repository 同时负责保存聚合和报表统计。
- 查询字段驱动聚合字段设计。
### 如何检查
检查 repository 方法按命令/查询职责分离情况。
### 反例
```java
Page<Payment> searchDashboard(Pageable pageable);
```
### 正例
```java
paymentQueryService.searchDashboard(query);
```

## DDD-INFRA-001 领域层不得依赖基础设施细节

### 规范说明
Domain 包不应依赖 Spring MVC、JPA Repository 实现、Redis、MQ SDK、HTTP client、JSON 框架或数据库注解。
### 检查点
- domain import `org.springframework.web`、`RedisTemplate`、`KafkaTemplate`。
- 领域对象上有 Web/JSON 序列化注解驱动业务。
- domain 直接调用外部 SDK。
### 如何检查
检查 domain 包 import。
### 反例
```java
class Payment { @Autowired RedisTemplate<String, String> redisTemplate; }
```
### 正例
```java
class Payment { void confirm(RiskDecision decision) {} }
```

## DDD-INFRA-002 DTO/Request/Response 不得进入领域层

### 规范说明
Web DTO、RPC DTO、数据库 PO 不应作为领域方法参数、字段或返回值。
### 检查点
- domain 方法接收 `*Request`、`*Response`、`*DTO`。
- DTO 注解驱动领域校验。
- 领域对象保存外部 payload。
### 如何检查
检查 domain/application 边界转换。
### 反例
```java
payment.apply(PayRequest request);
```
### 正例
```java
payment.apply(PayCommand command);
```

## DDD-INFRA-003 持久化模型与领域模型转换必须集中

### 规范说明
如果使用 PO/Entity 与 Domain 分离，转换应集中在 adapter/mapper，不能散落在多个 service 中。
### 检查点
- 多个 service 手写 PO 到 domain 转换。
- 转换遗漏字段或规则。
- domain 构造依赖数据库默认值。
### 如何检查
查找 `toDomain`、`fromEntity` 重复实现。
### 反例
```java
new Payment(entity.getId(), entity.getStatus(), entity.getAmount());
```
### 正例
```java
paymentPersistenceMapper.toDomain(entity);
```

## 领域事件

## DDD-EVENT-001 领域事件必须表达已发生事实

### 规范说明
领域事件命名和内容必须表达已经发生的业务事实，不能用命令式事件名表达待执行动作。
### 检查点
- `PayOrderEvent`、`CreateInvoiceEvent`。
- 事件表示希望别人做什么。
- 事件时态不是过去式。
### 如何检查
检查 Event 类名和发布位置。
### 反例
```java
eventPublisher.publish(new PayOrderEvent(order));
```
### 正例
```java
eventPublisher.publish(new OrderPaidEvent(order.id(), order.paidAt()));
```

## DDD-EVENT-002 事件内容应是快照或标识

### 规范说明
事件不应直接携带可变聚合、JPA Entity 或大对象图，应携带业务 ID、版本、关键快照和值对象。
### 检查点
- Event 字段是 Aggregate/Entity。
- 事件携带 lazy association。
- 消费方读取事件对象可变状态。
### 如何检查
检查事件字段和构造参数。
### 反例
```java
record OrderPaidEvent(Order order) {}
```
### 正例
```java
record OrderPaidEvent(OrderId orderId, Money paidAmount, Instant occurredAt) {}
```

## DDD-EVENT-003 事件发布时机必须与事务一致

### 规范说明
领域事件应在聚合状态持久化成功后可靠发布；事务内直接发送外部消息会导致状态与消息不一致。
### 检查点
- 保存前 publish。
- 事务内调用 MQ/HTTP。
- 失败后无法补偿。
### 如何检查
检查 save、commit、publish、send 的顺序。
### 反例
```java
mq.send(new OrderPaidEvent(order.id()));
orderRepository.save(order);
```
### 正例
```java
orderRepository.save(order);
outboxRepository.save(order.pullDomainEvents());
```

## DDD-EVENT-004 外部消息必须有可靠投递策略

### 规范说明
跨进程事件必须有 outbox、重试、去重、死信和可观测性，不能只调用一次发送接口。
### 检查点
- `kafkaTemplate.send` 后无 outbox。
- 无消息 ID/幂等键。
- 无失败处理。
### 如何检查
检查事件发布适配器。
### 反例
```java
kafkaTemplate.send(topic, event);
```
### 正例
```java
outbox.save(event.toMessage(messageId));
```

## DDD-EVENT-005 领域事件不得替代命令

### 规范说明
命令表示意图，事件表示事实。不能用事件对象作为输入命令驱动领域动作。
### 检查点
- service 接收 `*Event` 后修改本上下文聚合。
- 事件字段包含命令参数。
- 事件名是动词。
### 如何检查
检查 consumer/application 方法参数。
### 反例
```java
public void handle(PayOrderEvent event) { payment.pay(event.amount()); }
```
### 正例
```java
public void handle(OrderPaidEvent event) { settlement.startFor(event.orderId()); }
```

## DDD-EVENT-006 消费方幂等、重放、顺序语义必须明确

### 规范说明
事件消费者必须声明幂等键、重复消息、乱序、重放和补偿处理，尤其是支付、库存、积分、结算类事件。
### 检查点
- consumer 直接累加/扣减。
- 无 processed message 表或业务幂等键。
- 无版本或发生时间校验。
### 如何检查
检查事件 consumer 的保存和幂等逻辑。
### 反例
```java
points.add(event.userId(), event.points());
```
### 正例
```java
if (processedMessageRepository.markIfAbsent(event.messageId())) points.add(...);
```

## 分层架构

## DDD-LAYER-001 Controller 不能直接访问 Repository/Mapper

### 规范说明
入口层只负责协议适配、鉴权前置和参数转换，不应直接访问持久层或领域对象内部状态。
### 检查点
- Controller 注入 Repository/Mapper。
- Controller 调用 save/update/delete。
- Controller 组装领域规则。
### 如何检查
检查 `@Controller`、`@RestController` 字段和方法体。
### 反例
```java
@RestController class PayController { @Autowired PaymentRepository repository; }
```
### 正例
```java
@RestController class PayController { private final PayApplicationService service; }
```

## DDD-LAYER-002 Controller 不承载业务规则

### 规范说明
Controller 不应判断支付状态、库存策略、折扣、审批、结算等业务规则。
### 检查点
- Controller 中有领域状态 if/else。
- Controller 直接 set domain 字段。
- Controller 选择领域策略。
### 如何检查
检查 Controller 新增条件和状态变更。
### 反例
```java
if (request.amount().compareTo(limit) > 0) order.setStatus(REVIEW);
```
### 正例
```java
service.submitForPayment(request.toCommand());
```

## DDD-LAYER-003 Domain 不依赖 Application/Infrastructure

### 规范说明
依赖方向必须向内，Domain 不应 import application service、controller、repository implementation、mapper、client。
### 检查点
- domain import application/infra/web。
- domain 调用 service bean。
- domain 依赖 persistence entity。
### 如何检查
检查 domain 包 import。
### 反例
```java
import com.acme.payment.application.PaymentApplicationService;
```
### 正例
```java
import com.acme.payment.domain.policy.PaymentPolicy;
```

## DDD-LAYER-004 Infrastructure 实现接口，不污染领域模型

### 规范说明
基础设施层实现领域接口或应用端口，不应把技术对象反向传入领域层。
### 检查点
- infra 类型出现在 domain 方法签名。
- repository implementation 返回 ORM entity 给 domain。
- adapter 修改领域对象内部集合。
### 如何检查
检查 adapter/repository implementation 边界。
### 反例
```java
domainService.check(redisHashOperations);
```
### 正例
```java
domainService.check(cachePolicySnapshot);
```

## DDD-LAYER-005 禁止循环依赖和横向穿透

### 规范说明
Domain、Application、Infrastructure、Interfaces 之间必须保持单向依赖，禁止 service/repository/controller 互相循环调用。
### 检查点
- application 调 controller。
- repository 调 application service。
- 同层模块互相调用内部类。
### 如何检查
检查 import 和依赖注入字段。
### 反例
```java
class PaymentRepositoryImpl { @Autowired PaymentApplicationService service; }
```
### 正例
```java
class PaymentRepositoryImpl implements PaymentRepository {}
```

## 业务规则表达

## DDD-RULE-001 业务规则必须显式表达

### 规范说明
核心业务规则应由聚合、值对象、Policy、Specification 或领域服务显式命名和封装。
### 检查点
- 魔法数字/字符串表达规则。
- 重复条件散落。
- 规则没有命名。
### 如何检查
检查复杂条件和常量。
### 反例
```java
if (amount.compareTo(new BigDecimal("5000")) > 0 && level > 2) {}
```
### 正例
```java
if (largePaymentReviewPolicy.requiresReview(payment)) {}
```

## DDD-RULE-002 状态机必须集中建模

### 规范说明
生命周期状态流转应集中在聚合、状态机或 Policy 中，不能在多个 service、consumer、job 中复制。
### 检查点
- 多处判断当前状态并设置下一状态。
- 缺少非法流转异常。
- 新状态未覆盖所有流转。
### 如何检查
查找 status enum 使用点。
### 反例
```java
if (status == CREATED) status = PAID;
```
### 正例
```java
paymentStatusMachine.transition(current, event);
```

## DDD-RULE-003 业务异常必须表达领域语义

### 规范说明
领域层应抛出有业务含义的异常或结果，不能只抛 `RuntimeException`、`IllegalStateException` 或返回 false。
### 检查点
- 关键规则失败只抛通用异常。
- 异常消息无法映射业务原因。
- 上层无法区分失败类型。
### 如何检查
检查领域方法异常和 Result 类型。
### 反例
```java
throw new RuntimeException("invalid");
```
### 正例
```java
throw new PaymentAlreadyRefundedException(paymentId);
```

## DDD-RULE-004 关键规则变更必须可审计

### 规范说明
支付、风控、结算、权限、库存等关键规则变更应可追踪规则版本、决策原因和生效时间。
### 检查点
- 规则硬编码且无版本。
- 决策结果无 reason。
- 审计日志只有技术字段。
### 如何检查
检查 Policy、Rule、Decision 类和日志。
### 反例
```java
return amount.compareTo(limit) > 0;
```
### 正例
```java
return Decision.deny("LIMIT_EXCEEDED", policy.version());
```

## DDD-RULE-005 调用方约定不能替代领域保护

### 规范说明
不能靠注释、调用顺序或前端校验保证领域规则；领域对象必须防御非法输入和非法流转。
### 检查点
- 注释写“调用前需校验”。
- 只在 Controller 校验领域规则。
- 聚合方法无 guard。
### 如何检查
检查规则是否在领域层有最终保护。
### 反例
```java
// caller must ensure amount > 0
this.amount = amount;
```
### 正例
```java
this.amount = Money.positive(amount, currency);
```

## DDD-RULE-006 业务规则不得隐藏在数据库触发器或 SQL CASE

### 规范说明
核心领域规则不能只存在于 SQL、触发器、存储过程或 ORM 注解中，应用层领域模型必须表达相同语义。
### 检查点
- 状态计算只在 SQL CASE。
- 业务约束只靠 DB trigger。
- Java 领域模型无法说明规则。
### 如何检查
检查 repository SQL 和 domain 缺失规则。
### 反例
```sql
CASE WHEN amount > 1000 THEN 'REVIEW' ELSE 'PASS' END
```
### 正例
```java
riskReviewPolicy.decide(payment);
```

## CQRS

## DDD-CQRS-001 复杂查询不要污染聚合模型

### 规范说明
报表、搜索、运营后台、跨表聚合查询应使用 read model/query service，不应为了查询向聚合添加无关字段和集合。
### 检查点
- 聚合新增只为列表展示的字段。
- 聚合仓储承担报表查询。
- 查询 join 驱动领域模型结构。
### 如何检查
检查新增查询和聚合字段。
### 反例
```java
payment.setMerchantNameForDashboard(name);
```
### 正例
```java
paymentDashboardQuery.search(criteria);
```

## DDD-CQRS-002 read model 与 write model 职责分离

### 规范说明
写模型保护不变量，读模型服务查询展示。不能用读模型对象执行命令，也不能用写模型承载统计报表。
### 检查点
- View/DTO 进入 command 方法。
- read model 被保存为聚合。
- 写模型返回报表结构。
### 如何检查
检查 query package 和 command package 交叉使用。
### 反例
```java
paymentApplicationService.refund(paymentView);
```
### 正例
```java
paymentApplicationService.refund(new RefundCommand(paymentId, amount));
```

## DDD-CQRS-003 查询 DTO 不应反向进入领域命令

### 规范说明
查询 DTO 面向展示，字段可能冗余和扁平化，不能作为领域命令输入。
### 检查点
- `*View`、`*Response` 被 command service 接收。
- 查询字段影响状态变更。
- 缺少命令校验。
### 如何检查
检查 application command 方法参数。
### 反例
```java
public void approve(PaymentDetailView view) {}
```
### 正例
```java
public void approve(ApprovePaymentCommand command) {}
```

## DDD-CQRS-004 统计/报表逻辑不得破坏聚合边界

### 规范说明
统计和报表可以跨聚合读取，但不能借此跨聚合写入或修改聚合内部状态。
### 检查点
- 报表任务同时更新多个聚合。
- 查询结果反写领域状态。
- 批处理绕过应用服务。
### 如何检查
检查 report/job/scheduler 中的写操作。
### 反例
```java
for (ReportRow row : rows) paymentRepository.updateStatus(row.id(), row.status());
```
### 正例
```java
paymentApplicationService.reconcile(command);
```

## 演进与兼容

## DDD-EVO-001 新字段或新状态必须维护兼容语义

### 规范说明
新增领域字段、状态、类型必须定义默认值、迁移、旧数据解释和上下游兼容策略。
### 检查点
- 新状态未更新状态机。
- 新字段无默认和迁移。
- 旧事件/旧消息无法消费。
### 如何检查
检查 enum、schema、事件和转换代码。
### 反例
```java
enum PaymentStatus { CREATED, PAID, ARCHIVED }
```
### 正例
```java
PaymentStatus.fromPersisted(value).orElse(UNKNOWN);
```

## DDD-EVO-002 枚举扩展必须检查状态机和持久化兼容

### 规范说明
新增枚举值不仅是代码改动，还要检查数据库值、JSON 兼容、外部 API、状态流转和报表解释。
### 检查点
- 只新增 enum 常量。
- switch/default 吞掉未知状态。
- 持久化使用 ordinal。
### 如何检查
检查 enum 使用点和 persistence mapping。
### 反例
```java
@Enumerated(EnumType.ORDINAL)
private PaymentStatus status;
```
### 正例
```java
@Enumerated(EnumType.STRING)
private PaymentStatus status;
```

## DDD-EVO-003 删除、归档、撤销生命周期必须建模

### 规范说明
删除、归档、撤销、冻结、恢复等生命周期动作不能只做物理删除或状态覆盖，应表达业务含义和可恢复/审计策略。
### 检查点
- 直接 delete 聚合。
- `status = null` 表示归档。
- 无撤销原因和操作人。
### 如何检查
检查删除/归档/撤销新增逻辑。
### 反例
```java
paymentRepository.deleteById(id);
```
### 正例
```java
payment.archive(ArchiveReason.expired(), operator);
```

## DDD-EVO-004 领域规则版本必须可追踪

### 规范说明
当规则会影响钱、权限、风控、清结算或合约结果时，决策应记录规则版本和快照。
### 检查点
- 策略改动后无法解释旧结果。
- 决策记录没有 ruleVersion。
- 回放历史事件会使用新规则。
### 如何检查
检查 Decision、Event、Audit 字段。
### 反例
```java
decisionRepository.save(new Decision(result));
```
### 正例
```java
decisionRepository.save(new Decision(result, policy.version(), policy.snapshot()));
```

## 多租户与业务隔离

## DDD-TENANT-001 多租户/多商户隔离必须是领域概念

### 规范说明
租户、商户、机构、渠道等隔离边界应作为值对象和聚合不变量，不能只依赖 SQL where 或 Controller 参数。
### 检查点
- 聚合缺少 tenantId/merchantId。
- repository 查询才补租户条件。
- 应用服务可任意 reassign merchant。
### 如何检查
检查聚合字段、命令对象和 repository 方法。
### 反例
```java
payment.setMerchantId(request.merchantId());
```
### 正例
```java
payment.transferToMerchant(MerchantId target, MerchantTransferPolicy policy);
```

## DDD-TENANT-002 跨租户引用必须显式授权和建模

### 规范说明
跨租户、跨商户、跨机构引用不能只是两个 ID 同时出现，必须有业务关系、授权策略和审计。
### 检查点
- command 同时接收 sourceTenantId/targetTenantId。
- 无授权策略对象。
- 无关系模型。
### 如何检查
检查迁移、转移、共享、代运营场景。
### 反例
```java
shareResource(String sourceTenantId, String targetTenantId, String resourceId);
```
### 正例
```java
tenantSharingService.share(new ShareResourceCommand(source, target, resourceId), sharingPolicy);
```

## DDD-TENANT-003 缓存和事件 key 必须包含领域隔离维度

### 规范说明
领域缓存、幂等键、事件 key、读模型 key 必须包含租户、商户、上下文和版本等隔离维度。
### 检查点
- key 只有业务 ID。
- `"active"`、`"current"` 作为全局 key。
- 事件 key 缺少 tenantId。
### 如何检查
检查 cache、outbox、message key。
### 反例
```java
cache.put("active", policy);
```
### 正例
```java
cache.put(policyKey(tenantId, merchantId, policyId, version), policy);
```
