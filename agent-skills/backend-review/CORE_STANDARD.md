# Backend Core Standard

## 规范说明
只报告后端 API 契约、事务、幂等、错误处理、后台任务和集成可靠性问题。

## 检查点
- 写接口是否幂等、防重复提交和事务一致。
- API 兼容性、错误码和响应结构是否破坏调用方。
- 后台任务是否可重试、可观测、可恢复。

## 如何检查
1. 定位 Controller/ApplicationService/Job 变更。
2. 检查事务边界和外部系统调用。
3. 判断是否影响调用方契约。

## 反例
```java
paymentGateway.charge(req); repository.save(order);
```

## 正例
```java
repository.savePending(order); outbox.enqueueCharge(order.id());
```
