# Security Agent Java Web 代码规范

适用专家：Security Agent

适用范围：Java / Spring Web 项目的认证、授权、注入、敏感信息、反序列化、重定向、文件上传、安全配置和依赖安全。

排除范围：性能优化、DDD 设计、普通编码风格、测试覆盖、Redis 一致性和前端交互问题。

## 输出要求

每个问题必须包含：

- 精确 `file_path`
- 精确 `line_start` / `line_end`
- 触发的 `rule_id`
- 具体攻击场景或泄漏路径
- 建议修改代码
- 相关工具证据，优先使用 Semgrep、FindSecBugs、Dependency-Check、gitleaks

## SEC-AUTHN-001 管理和敏感接口必须认证

### 规范说明

新增管理、配置、资金、用户数据、订单状态、权限变更类接口必须能证明调用者已完成身份认证。

### 检查点

- Controller 方法是否暴露 `@GetMapping`、`@PostMapping`、`@PutMapping`、`@DeleteMapping`。
- 方法是否处于公开白名单路径。
- 是否存在 `@PreAuthorize`、`@Secured`、网关拦截器、登录态上下文或明确认证校验。
- 是否存在 `permitAll()`、`anonymous()`、未受保护的 actuator 或 admin 路由。

### 如何检查

1. 用 tree-sitter 提取新增 Controller 路由。
2. 读取 Spring Security 配置和路由白名单。
3. 对敏感路径检查认证证据。
4. 若仅依赖前端隐藏按钮，必须判为问题。

### 反例

```java
@PostMapping("/admin/users/{id}/disable")
public void disableUser(@PathVariable Long id) {
    userService.disable(id);
}
```

### 正例

```java
@PreAuthorize("hasAuthority('USER_ADMIN')")
@PostMapping("/admin/users/{id}/disable")
public void disableUser(@PathVariable Long id) {
    userService.disable(id);
}
```

## SEC-AUTHZ-002 资源访问必须校验归属和权限

### 规范说明

凡是通过 path/query/body 传入用户、租户、项目、订单、账户等资源 ID 的接口，必须校验当前用户是否有权访问该资源。

### 检查点

- 是否直接使用 `userId`、`tenantId`、`projectId`、`orderId` 查询或更新。
- 是否从请求参数读取归属字段而不是从登录上下文读取。
- 是否校验资源 owner、tenant、organization 或 role。

### 如何检查

1. 找到新增接口的 ID 参数。
2. 跟踪到 Service 调用。
3. 查找 `permissionService`、`ownership`、`tenant`、`authContext` 等校验。
4. 没有服务端归属校验时输出 finding。

### 反例

```java
@PutMapping("/orders/{orderId}/status")
public void updateStatus(@PathVariable Long orderId, @RequestBody StatusRequest req) {
    orderService.updateStatus(orderId, req.status());
}
```

### 正例

```java
@PutMapping("/orders/{orderId}/status")
public void updateStatus(@PathVariable Long orderId, @RequestBody StatusRequest req) {
    Long currentUserId = authContext.currentUserId();
    orderPermissionService.requireCanUpdate(currentUserId, orderId);
    orderService.updateStatus(orderId, req.status());
}
```

## SEC-INJECT-003 禁止 SQL/JPQL/MyBatis 字符串拼接

### 规范说明

外部输入不得拼接进 SQL、JPQL、MyBatis `${}`、JDBC Statement 或动态查询字符串。

### 检查点

- `Statement.executeQuery(sql + input)`
- `entityManager.createQuery("... " + param)`
- MyBatis XML 中 `${param}`
- `@Query` 拼接外部输入
- order by、sort、column 参数未白名单

### 如何检查

1. Semgrep / FindSecBugs 命中 SQL 注入候选。
2. 检查变量是否来自 request、DTO、path、query。
3. 检查是否使用参数绑定或白名单枚举。

### 反例

```java
String sql = "select * from orders where user_id = " + request.getUserId();
statement.executeQuery(sql);
```

### 正例

```java
PreparedStatement ps = connection.prepareStatement(
    "select * from orders where user_id = ?"
);
ps.setLong(1, request.getUserId());
```

## SEC-SECRET-004 禁止明文密钥和敏感信息进入代码

### 规范说明

源码、配置、日志、异常和测试数据中不得新增真实 token、password、secret、AK/SK、私钥、webhook token。

### 检查点

- `application*.yml/properties` 中新增密码。
- Java 常量中出现 token、secret、privateKey。
- 日志输出 Authorization、Cookie、身份证、手机号、银行卡。
- gitleaks / TruffleHog 命中。

### 如何检查

1. 使用 gitleaks 和中文云厂商扩展规则扫描 diff。
2. 对日志语句检查是否输出 DTO 或 header 全量对象。
3. 对异常响应检查是否回显敏感字段。

### 反例

```java
private static final String ACCESS_KEY = "LTAIxxxxxxxxxxxx";
log.info("login request={}", request);
```

### 正例

```java
private final String accessKey = secretProvider.get("oss.access-key");
log.info("login request userId={}, channel={}", request.userId(), request.channel());
```

## SEC-DESER-005 禁止不可信反序列化和危险类型解析

### 规范说明

不得对外部输入直接使用 Java 原生反序列化、Fastjson autoType、XStream、SnakeYAML 任意类型解析。

### 检查点

- `ObjectInputStream.readObject`
- `JSON.parseObject(input, clazz)` 对外部输入无白名单
- Fastjson autoType 开启
- YAML/XML 解析器未关闭外部实体

### 如何检查

1. 使用 Semgrep / FindSecBugs 检测危险 API。
2. 判断输入是否来自 HTTP、MQ、文件上传、Redis、第三方回调。
3. 检查是否有类型白名单、签名校验和安全 parser 配置。

### 反例

```java
ObjectInputStream in = new ObjectInputStream(request.getInputStream());
Object payload = in.readObject();
```

### 正例

```java
PaymentCallback payload = objectMapper.readValue(body, PaymentCallback.class);
callbackSignatureVerifier.verify(headers, body);
```

## SEC-FILE-006 文件上传和下载必须限制路径、类型和大小

### 规范说明

文件操作不得信任用户传入的文件名、路径、content-type 或扩展名。

### 检查点

- 是否存在路径穿越：`../`、绝对路径、用户传 path。
- 是否限制文件大小、扩展名、MIME 和存储目录。
- 下载接口是否校验文件归属。
- 上传后是否执行或解析高风险内容。

### 如何检查

1. 查找 `MultipartFile`、`Files.write`、`Resource`、`FileInputStream`。
2. 检查路径是否由服务端生成。
3. 检查下载是否做权限校验。

### 反例

```java
Path target = Paths.get(uploadDir, file.getOriginalFilename());
file.transferTo(target);
```

### 正例

```java
String safeName = fileNamePolicy.generate(file.getOriginalFilename());
fileTypePolicy.requireAllowed(file);
Path target = storageRoot.resolve(safeName).normalize();
```

## SEC-CONFIG-007 Spring 安全配置不得暴露危险默认值

### 规范说明

Spring Security、Actuator、CORS、Cookie、CSRF、debug 配置必须使用安全默认值。

### 检查点

- `management.endpoints.web.exposure.include=*`
- 全局 `csrf().disable()` 没有 API 场景说明。
- CORS `allowedOrigins("*")` 且允许凭证。
- Cookie 缺少 `HttpOnly`、`Secure`、`SameSite`。
- 开启远程 debug 或 actuator 未鉴权。

### 如何检查

1. 扫描 Java config 和 `application*.yml`。
2. 使用 Trivy config / Semgrep Spring 规则。
3. 判断是否为本地 profile，生产 profile 命中必须输出。

### 反例

```yaml
management:
  endpoints:
    web:
      exposure:
        include: "*"
```

### 正例

```yaml
management:
  endpoints:
    web:
      exposure:
        include: "health,prometheus"
```
