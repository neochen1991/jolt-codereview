# DDD Java Standard

## 规范说明
适用于 Java / Spring 分层项目，关注 Controller、ApplicationService、Domain、Repository 的职责边界。

## 检查点
- Controller 不应直接修改 Entity 状态。
- Repository 不应承载业务规则。
- 领域事件应表达业务事实而不是技术动作。

## 如何检查
1. 检查新增 service/entity/repository 文件。
2. 对照调用链确认规则执行位置。
3. 找到绕过聚合方法的 setter 或贫血模型证据。

## 反例
```java
payment.setStatus(SUCCESS);
```

## 正例
```java
payment.confirmSuccess(receiptNo);
```
