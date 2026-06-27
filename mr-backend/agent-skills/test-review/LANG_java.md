# Test Java Standard

## 规范说明
适用于 JUnit、Mockito、SpringBootTest 等 Java 测试。

## 检查点
- Controller 权限变更应有 401/403 测试。
- Repository/Service 边界条件应有断言。
- Mock 不应掩盖被测逻辑。

## 如何检查
1. 搜索同名 `*Test` 和 `src/test`。
2. 检查断言是否覆盖状态、异常和副作用。
3. 对高风险变更要求至少一条回归用例。

## 反例
```java
verify(service).create(any());
```

## 正例
```java
assertThat(response.getStatusCode()).isEqualTo(FORBIDDEN);
```
