# Test Core Standard

## 规范说明
只报告测试覆盖、断言质量、回归风险、边界场景和测试可维护性问题。

## 检查点
- 新增业务分支是否有对应测试。
- 测试是否断言结果而不是只执行代码。
- 错误路径、权限路径和边界输入是否覆盖。

## 如何检查
1. 对比生产代码和测试文件。
2. 查找新增规则但无同名测试。
3. 识别无断言、过度 mock 或只测 happy path。

## 反例
```java
service.create(request);
```

## 正例
```java
assertThrows(ForbiddenException.class, () -> service.create(request));
```
