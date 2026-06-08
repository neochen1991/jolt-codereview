# DDD Core Standard

## 规范说明
只报告领域模型、聚合边界、业务不变量、上下文边界和领域事件表达问题。

## 检查点
- 聚合不变量是否在聚合内维护。
- 应用服务是否承载过多领域决策。
- 值对象、实体、领域服务职责是否混淆。

## 如何检查
1. 定位 domain/application/repository 变更。
2. 查找业务规则散落在 Controller 或基础设施层的证据。
3. 判断是否造成不变量绕过或上下文耦合。

## 反例
```java
order.setStatus(PAID); order.setPaidAt(now);
```

## 正例
```java
order.markPaid(paymentId, now);
```
