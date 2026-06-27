# Backend Java Standard

## 规范说明
适用于 Java / Spring 后端服务，结合华为 CodeArts Check 公开规则集方向、企业 Java Web 分层约束和阿里巴巴 Java 编码规约中 Web/ORM 相关规则。Backend Agent 只关注接口契约、分层边界、事务、幂等、ORM 参数绑定和请求链路可靠性，不重复检查通用语言规范、Redis 专项、依赖漏洞和测试覆盖专项。

## 检查点
- Controller 入参使用 `@RequestBody` 时必须有 `@Valid` 或等价校验。
- POST/PUT/PATCH/DELETE 等副作用接口必须有 request id、幂等键、业务唯一键或状态机防重。
- Controller 不得直接依赖 Repository/Mapper，必须通过应用服务编排业务、事务和鉴权。
- `@Transactional` 不得标注在 `private`、`final`、`static` 方法上，事务边界应位于 public 应用服务方法。
- `@Transactional` 边界内避免远程调用、阻塞等待和不可控外部副作用。
- Controller/Service 请求链路不得使用 `Thread.sleep` 作为等待、重试或限流机制。
- 异常映射不应把内部堆栈、SQL、路径、类名或原始 message 返回给调用方。
- MyBatis/iBatis SQL 参数必须使用 `#{}` 绑定，`${}` 只能用于白名单枚举后的表名或排序字段。
- 数据库查询结果不得使用 `HashMap`、`Hashtable`、裸 `Map` 承载业务字段。
- iBatis `queryForList(statement, start, size)` 不得作为大数据分页方式，应改为数据库侧分页。

## 如何检查
1. 搜索 Controller 写接口、`@RequestBody`、`@Valid`、`Idempotency-Key`、`requestId` 和业务唯一键。
2. 搜索 Controller 中的 `Repository`、`Mapper`，确认是否绕过 Service。
3. 搜索 `@Transactional`，检查后续方法签名是否为 `private`、`final`、`static`，以及事务内是否含远程调用或阻塞等待。
4. 搜索 Mapper XML/注解 SQL 中的 `${}`、`resultType="HashMap"`、`queryForList(`。
5. 对每个问题给出精确行号、命中的规范条目、可替换建议代码和必要的回归测试建议。

## 反例
```java
@RestController
class PaymentController {
    private final PaymentMapper paymentMapper;

    @PostMapping("/pay")
    public void pay(@RequestBody PayRequest req) throws InterruptedException {
        Thread.sleep(1000);
        paymentMapper.insert(req);
    }
}
```

```xml
<select id="findByUser" resultType="java.util.HashMap">
  SELECT * FROM payment WHERE user_id = ${userId}
</select>
```

## 正例
```java
@RestController
class PaymentController {
    private final PaymentService paymentService;

    @PostMapping("/pay")
    public void pay(
        @RequestHeader("Idempotency-Key") String key,
        @Valid @RequestBody PayRequest req
    ) {
        paymentService.pay(key, req);
    }
}

class PaymentService {
    @Transactional
    public void pay(String requestId, PayRequest req) {
        idempotencyGuard.executeOnce(requestId, () -> paymentRepository.save(req));
    }
}
```

```xml
<select id="findByUser" resultType="com.jolt.payment.PaymentRecord">
  SELECT id, user_id, amount
  FROM payment
  WHERE user_id = #{userId}
  LIMIT #{size} OFFSET #{start}
</select>
```
