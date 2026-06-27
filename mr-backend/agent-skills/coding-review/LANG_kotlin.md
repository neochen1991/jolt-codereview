# Coding Kotlin Standard

## 规范说明
适用于 Kotlin 服务代码的通用正确性检视。

## 检查点
- nullable 类型必须显式处理，避免 `!!`。
- 协程必须绑定 scope，不得泄漏。
- 数据类和 sealed class 应表达状态约束。

## 如何检查
1. 搜索 `!!`、`GlobalScope`、空集合访问。
2. 检查 suspend 调用异常传播。
3. 检查状态建模是否允许非法组合。

## 反例
```kotlin
val id = request.user!!.id
```

## 正例
```kotlin
val user = request.user ?: throw UnauthorizedException()
val id = user.id
```
