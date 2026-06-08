# Security Java Standard

## 规范说明
适用于 Java / Spring Web 安全检视，优先检查 Controller、Filter、SecurityConfig、配置文件和依赖声明。

## 检查点
- `@GetMapping` / `@PostMapping` 等敏感接口必须有 `@PreAuthorize`、拦截器或服务端权限校验。
- JDBC、JPA native query、MyBatis `${}` 不得拼接用户输入。
- `application*.yml` 不得暴露密码、actuator 全开放或危险默认配置。

## 如何检查
1. 定位新增 Spring 路由和配置。
2. 查找 `permitAll`、`management.endpoints.web.exposure.include=*`、`${}`、字符串 SQL。
3. 结合 Semgrep、gitleaks、依赖工具观察确认风险。

## 反例
```java
@PostMapping("/projects/{id}/settings")
public void update(@PathVariable Long id) { service.update(id); }
```

## 正例
```java
@PreAuthorize("hasAuthority('PROJECT_ADMIN')")
@PostMapping("/projects/{id}/settings")
public void update(@PathVariable Long id) { service.update(id); }
```
