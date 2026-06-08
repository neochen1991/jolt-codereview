from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from calibration.precision_history import calibrate_findings_with_history, load_rule_precision_history
from diff.slicer import extract_added_lines
from tools.tool_normalizer import CATEGORY_PRIMARY_RULE, canonical_rule_id, line_bucket, normalize_tool_finding, normalized_rule_category, sha1

SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
SELECTABLE_SEVERITIES = {"critical", "high", "medium"}
OSS_TOOL_PROMOTION_THRESHOLDS = {
    "semgrep": 0.76,
    "pmd": 0.75,
    "checkstyle": 0.82,
    "spotbugs": 0.78,
    "dependency-check": 0.78,
    "osv": 0.78,
    "trivy": 0.78,
    "kics": 0.8,
    "openapi-diff": 0.8,
    "gitleaks": 0.82,
}
PROMOTABLE_TOOL_RULES = {
    "BE-API-001",
    "BE-IDEMP-004",
    "BE-TX-002",
    "CODE-EXC-003",
    "CODE-NULL-001",
    "CODE-RESOURCE-005",
    "CODE-STATE-004",
    "DB-DDL-001",
    "DB-NOTNULL-002",
    "DDD-AGG-001",
    "DDD-VO-002",
    "DEP-CVE-001",
    "DEP-SCOPE-005",
    "JOLT_JAVA_FIELD_AUTOWIRED",
    "PERF-LIKE-002",
    "PERF-MEM-004",
    "PERF-QUERY-001",
    "REDIS-CMD-003",
    "REDIS-TTL-002",
    "SEC-CONFIG-007",
    "SEC-CRYPTO-010",
    "SEC-DEBUG-011",
    "SEC-AUTHN-001",
    "SEC-AUTHZ-002",
    "SEC-INJECT-003",
    "SEC-RISK-006",
    "SEC-SECRET-004",
    "SEC-SECRET-004:ERROR_RESPONSE",
    "SEC-SSRF-009",
    "SEC-WEBHOOK-008",
    "TEST-COVER-001",
    "ALI-BIGDECIMAL-001",
    "ALI-CONCURRENCY-001",
    "ALI-CONCURRENCY-002",
    "ALI-CONCURRENCY-003",
    "ALI-DB-001",
    "ALI-DB-002",
    "ALI-EQUALS-001",
    "ALI-EXC-002",
    "ALI-LOG-001",
    "ALI-MYBATIS-001",
    "ALI-NAMING-001",
    "ALI-NAMING-002",
    "ALI-RETURN-001",
    "HW-LAYER-001",
    "HW-PERF-001",
    "HW-SEC-001",
    "HW-TX-001",
}

PROMOTABLE_EXTERNAL_TOOL_RULES = {
    "AvoidCatchingGenericException": "CODE-EXC-003",
    "CloseResource": "CODE-RESOURCE-005",
}

AGENT_BY_RULE_PREFIX = {
    "BE-": "backend_agent",
    "CODE-": "coding_agent",
    "DB-": "database_agent",
    "DDD-": "ddd_agent",
    "DEP-": "dependency_agent",
    "PERF-": "performance_agent",
    "REDIS-": "redis_agent",
    "SEC-": "security_agent",
    "TEST-": "test_agent",
    "ALI-": "coding_agent",
    "HW-": "backend_agent",
}

AGENT_BY_RULE = {
    "JOLT_JAVA_FIELD_AUTOWIRED": "coding_agent",
    "HW-SEC-001": "security_agent",
    "HW-PERF-001": "performance_agent",
    "HW-LAYER-001": "backend_agent",
    "HW-TX-001": "backend_agent",
    "ALI-CONCURRENCY-001": "performance_agent",
    "ALI-CONCURRENCY-003": "coding_agent",
    "SEC-CRYPTO-010": "security_agent",
    "SEC-DEBUG-011": "security_agent",
    "ALI-DB-001": "database_agent",
    "ALI-DB-002": "database_agent",
    "ALI-MYBATIS-001": "security_agent",
    "PERF-LIKE-002": "performance_agent",
}

RULE_REMEDIATION = {
    "BE-API-001": {
        "title": "接口 RequestBody 缺少 Bean Validation",
        "recommendation": "将 Map/Object 入参改为明确 DTO，并在 @RequestBody 前添加 @Valid；DTO 字段使用 @NotBlank、@NotNull 等约束。",
        "suggested_code": '''public Map<String, Object> search(@Valid @RequestBody PaymentSearchRequest request) {
    return paymentQueryService.searchByUser(request.userId());
}

public record PaymentSearchRequest(@NotBlank String userId) {}''',
    },
    "BE-IDEMP-004": {
        "title": "POST 副作用接口缺少幂等保护",
        "recommendation": "对写接口接入 Idempotency-Key/requestId 去重，或在业务唯一键上实现幂等状态机。",
        "suggested_code": '''String requestId = request.getHeader("Idempotency-Key");
idempotencyGuard.executeOnce(requestId, () -> {
    paymentService.process(command);
});''',
    },
    "CODE-NULL-001": {
        "title": "Map 入参字段缺少显式空值和类型校验",
        "recommendation": "使用 DTO + Bean Validation，或对 Map 字段做显式 required/type 校验后再进入业务逻辑。",
        "suggested_code": '''String userId = requireText(payload, "userId");''',
    },
    "CODE-RESOURCE-005": {
        "title": "JDBC 资源未使用 try-with-resources 关闭",
        "recommendation": "使用 try-with-resources 管理 Statement、ResultSet、Connection，确保异常路径也能释放资源。",
        "suggested_code": '''try (Statement statement = connection.createStatement();
     ResultSet rs = statement.executeQuery(sql)) {
    // consume result set
}''',
    },
    "PERF-QUERY-001": {
        "title": "查询缺少分页或结果上限",
        "recommendation": "为查询增加分页、LIMIT 或游标边界，禁止在接口中返回无上限结果集。",
        "suggested_code": '''PreparedStatement ps = connection.prepareStatement(
    "select id, amount from payments where user_id = ? order by id desc limit ?"
);''',
    },
    "PERF-LIKE-002": {
        "title": "LIKE 前导通配符导致索引失效",
        "recommendation": "避免 `LIKE '%xxx%'` 这类前导通配查询；改用精确匹配、前缀匹配、全文索引或受控搜索服务，并补充分页上限。",
        "suggested_code": '''PreparedStatement ps = connection.prepareStatement(
    "select id, amount from payment_orders where merchant_id = ? order by created_at desc limit ?"
);''',
    },
    "SEC-INJECT-003": {
        "title": "SQL 使用字符串拼接存在注入风险",
        "recommendation": "改用 PreparedStatement、MyBatis #{} 或类型安全查询构造器；动态排序、字段名、表名必须使用白名单。",
        "suggested_code": '''String sql = "select id, amount from payments where user_id = ? order by created_at desc limit ?";
try (PreparedStatement ps = connection.prepareStatement(sql)) {
    ps.setString(1, userId);
    ps.setInt(2, pageSize);
    try (ResultSet rs = ps.executeQuery()) {
        // map rows
    }
}''',
    },
    "REDIS-CMD-003": {
        "title": "生产路径使用 Redis KEYS 命令",
        "recommendation": "用 SCAN 分批遍历，或维护业务索引集合，避免 KEYS 阻塞 Redis 主线程。",
        "suggested_code": '''ScanOptions options = ScanOptions.scanOptions().match("payment:*:processing").count(500).build();
try (Cursor<byte[]> cursor = redisConnection.scan(options)) {
    while (cursor.hasNext()) {
        redisTemplate.delete(new String(cursor.next(), StandardCharsets.UTF_8));
    }
}''',
    },
    "REDIS-TTL-002": {
        "title": "Redis 缓存写入缺少 TTL",
        "recommendation": "为缓存类 key 设置明确过期时间；永久 key 需要在代码注释和规范中说明例外原因。",
        "suggested_code": '''redisTemplate.opsForValue().set(
    "payment:last:" + orderNo,
    value,
    Duration.ofMinutes(30)
);''',
    },
    "DDD-VO-002": {
        "title": "领域模型使用弱类型 Map 表达业务属性",
        "recommendation": "将 Map<String,Object> 替换为明确值对象或类型化字段，聚合根只暴露业务语义方法。",
        "suggested_code": '''private PaymentAttributes attributes;

public record PaymentAttributes(String channel, String scene) {}''',
    },
    "DDD-AGG-001": {
        "title": "聚合归属或状态被外部任意改写",
        "recommendation": "聚合根应通过显式业务方法维护状态和归属不变量；禁止暴露通用 override/reassign 方法直接改写商户归属或终态。",
        "suggested_code": '''public void transferMerchant(MerchantId targetMerchant, Operator operator) {
    ownershipPolicy.requireTransferAllowed(this, targetMerchant, operator);
    this.merchantId = targetMerchant.value();
}''',
    },
    "SEC-SECRET-004": {
        "title": "配置或代码中包含明文密钥",
        "recommendation": "删除仓库中的明文密码，改为环境变量、密钥管理服务或平台配置，并轮换已暴露凭据。",
        "suggested_code": '''spring:
  datasource:
    password: ${PAYMENT_DB_PASSWORD}''',
    },
    "SEC-CONFIG-007": {
        "title": "生产配置暴露敏感运行时信息",
        "recommendation": "关闭生产环境 SQL 明文日志、错误消息和堆栈回显；如确需排障，使用受控 profile、短期开关和脱敏日志。",
        "suggested_code": '''spring:
  jpa:
    show-sql: false
server:
  error:
    include-message: never
    include-stacktrace: never''',
    },
    "SEC-RISK-006": {
        "title": "客户端可控字段绕过风控",
        "recommendation": "风控跳过只能由服务端授权策略、灰度配置或审批上下文决定，禁止从客户端请求字段或可伪造 IP 直接绕过。",
        "suggested_code": '''boolean bypassAllowed = riskBypassPolicy.canBypass(operatorContext, order);
if (!bypassAllowed && risks.isRisky(order)) {
    throw new ApiException(HttpStatus.FORBIDDEN, "Risk check failed");
}''',
    },
    "SEC-WEBHOOK-008": {
        "title": "Webhook 签名校验不可信",
        "recommendation": "使用提供方约定的 HMAC/公钥签名校验，并加入时间戳、nonce 或事件幂等防重放；禁止 startsWith/contains 等字符串信任。",
        "suggested_code": '''boolean trusted = webhookVerifier.verify(
    request.rawPayload(),
    signature,
    request.timestamp()
);
if (!trusted) {
    throw new ApiException(HttpStatus.UNAUTHORIZED, "Invalid webhook signature");
}''',
    },
    "SEC-CRYPTO-010": {
        "title": "安全签名比较未使用常量时间算法",
        "recommendation": "签名、HMAC、摘要或 token 比较必须使用常量时间比较，并结合 HMAC-SHA256/密钥管理避免弱摘要。",
        "suggested_code": '''byte[] expectedBytes = expectedSignature.getBytes(StandardCharsets.UTF_8);
byte[] actualBytes = signature.getBytes(StandardCharsets.UTF_8);
if (!MessageDigest.isEqual(expectedBytes, actualBytes)) {
    throw new ApiException(HttpStatus.UNAUTHORIZED, "Invalid signature");
}''',
    },
    "SEC-DEBUG-011": {
        "title": "生产接口暴露调试状态",
        "recommendation": "删除生产调试接口，或至少增加强认证授权、环境开关和敏感字段脱敏。",
        "suggested_code": '''@PreAuthorize("hasAuthority('SYSTEM_DEBUG_VIEW')")
@GetMapping("/debug")
Map<String, Object> debugState() {
    return debugStateSanitizer.redactedState();
}''',
    },
    "SEC-SSRF-009": {
        "title": "用户可控回调地址触发服务端外连",
        "recommendation": "回调地址必须进行协议、域名白名单、DNS/IP 段、重定向和超时校验，禁止请求内网、环回地址或云元数据地址。",
        "suggested_code": '''URI callback = callbackUrlValidator.requireAllowed(order.getCallbackUrl());
restTemplate.postForEntity(callback, safePayload, String.class);''',
    },
    "DB-DDL-001": {
        "title": "迁移脚本包含破坏性 DDL",
        "recommendation": "DROP COLUMN 应拆成兼容迁移：先停止写入旧列、发布观察窗口，再在确认无依赖后单独删除。",
        "suggested_code": '''-- phase 1: keep legacy column, stop writing it in application code
-- phase 2 after verification window:
-- ALTER TABLE payments DROP COLUMN legacy_channel;''',
    },
    "DEP-CVE-001": {
        "title": "依赖组件存在已知漏洞",
        "recommendation": "升级到修复版本，必要时排除传递依赖，并用 trivy/osv/dependency-check 复扫确认。",
        "suggested_code": '''<!-- 将受影响依赖升级到 OSV/Trivy/Dependency-Check 给出的 fixed version -->
<dependency>
  <groupId>affected.group</groupId>
  <artifactId>affected-artifact</artifactId>
  <version>fixed.version</version>
</dependency>''',
    },
    "PERF-MEM-004": {
        "title": "结果集无上限累积到内存对象",
        "recommendation": "限制单次读取行数，使用分页返回，或采用流式处理并设置最大结果窗口。",
        "suggested_code": '''int count = 0;
while (rs.next() && count++ < pageSize) {
    response.put(rs.getString("id"), rs.getBigDecimal("amount"));
}''',
    },
    "ALI-BIGDECIMAL-001": {
        "title": "BigDecimal 不应使用 double/float 构造",
        "recommendation": "使用字符串构造或 BigDecimal.valueOf，并统一金额精度和舍入模式。",
        "suggested_code": '''public BigDecimal normalize(BigDecimal amount) {
    if (amount == null) {
        throw new IllegalArgumentException("amount required");
    }
    return amount.setScale(2, RoundingMode.HALF_UP);
}''',
    },
    "ALI-CONCURRENCY-001": {
        "title": "禁止直接使用 Executors 创建线程池",
        "recommendation": "显式使用 ThreadPoolExecutor，配置有界队列、线程数、拒绝策略和线程命名。",
        "suggested_code": '''ThreadPoolExecutor executor = new ThreadPoolExecutor(
    corePoolSize,
    maxPoolSize,
    60L,
    TimeUnit.SECONDS,
    new ArrayBlockingQueue<>(queueSize),
    new ThreadPoolExecutor.CallerRunsPolicy()
);''',
    },
    "ALI-CONCURRENCY-002": {
        "title": "共享非线程安全对象",
        "recommendation": "Spring 单例中的 static 可变集合和 SimpleDateFormat 需要替换为线程安全、可控生命周期的实现。",
        "suggested_code": '''private static final DateTimeFormatter WINDOW_FORMAT =
    DateTimeFormatter.ofPattern("yyyyMMdd-HHmm", Locale.US).withZone(ZoneId.of("Asia/Shanghai"));

private final Cache<TenantKey, List<String>> auditCache = Caffeine.newBuilder()
    .maximumSize(10_000)
    .expireAfterWrite(Duration.ofMinutes(30))
    .build();''',
    },
    "ALI-CONCURRENCY-003": {
        "title": "ThreadLocal 上下文未清理或跨线程读取",
        "recommendation": "请求线程写入 ThreadLocal 后必须在 finally 中 remove；后台任务应显式传参，不要读取请求线程 ThreadLocal。",
        "suggested_code": '''try {
    CURRENT_OPERATOR.set(operatorId);
    return doAudit(paymentId, operatorId, request);
} finally {
    CURRENT_OPERATOR.remove();
}

executor.execute(() -> jdbcGateway.writeBalanceAdjustment(merchantId, fee, operatorId, Instant.now(clock)));''',
    },
    "ALI-MYBATIS-001": {
        "title": "MyBatis SQL 中使用 ${} 存在注入风险",
        "recommendation": "将 `${}` 改为 `#{}` 参数绑定；动态排序/表名等必须使用白名单。",
        "suggested_code": '''WHERE user_id = #{userId}''',
    },
    "HW-LAYER-001": {
        "title": "Controller 不应直接依赖 Repository/Mapper",
        "recommendation": "Controller 只依赖应用服务，由 Service 编排 Repository/Mapper 和领域逻辑。",
        "suggested_code": '''private final PaymentService paymentService;''',
    },
}


def _rule_key(finding: dict[str, Any]) -> str:
    covered = finding.get("covered_rules") or []
    if isinstance(covered, list) and covered:
        return ",".join(sorted(str(item) for item in covered))
    return ""


def _primary_rule_key(finding: dict[str, Any]) -> str:
    covered = [str(item) for item in (finding.get("covered_rules") or []) if item]
    if covered:
        return covered[0]
    return str(finding.get("tool_rule_id") or finding.get("rule_id") or finding.get("normalized_rule_category") or "")


def _dedupe_key(finding: dict[str, Any]) -> tuple[str, str, int]:
    item = normalize_tool_finding(finding)
    return (
        str(item.get("normalized_rule_category") or item.get("tool_rule_id") or item.get("title") or ""),
        str(item.get("file_path") or ""),
        line_bucket(item.get("line_start")),
    )


def _semantic_category_group(category: str) -> str:
    if category in {"UNBOUNDED_QUERY", "UNBOUNDED_RESULT_MEMORY", "DB_MAP_RESULT_TYPE", "IBATIS_MEMORY_PAGINATION"}:
        return "UNBOUNDED_DATA_ACCESS"
    if category in {"SECRET_LEAK"}:
        return "SENSITIVE_DATA_EXPOSURE"
    if category in {"SPRING_VALIDATION", "NULL_SAFETY"}:
        return "INPUT_VALIDATION"
    return category


def _text_blob(finding: dict[str, Any]) -> str:
    return " ".join(
        str(finding.get(key) or "")
        for key in ["title", "problem_description", "recommendation", "evidence", "file_path", "tool_rule_id", "rule_id"]
    ).lower()


def _root_cause_signature(finding: dict[str, Any]) -> str | None:
    text = _text_blob(finding)
    path = str(finding.get("file_path") or "").replace("\\", "/").lower()
    if any(marker in text for marker in ["connection", "statement", "resultset", "autocommit", "jdbc", "连接", "连接池", "资源"]):
        if any(marker in text for marker in ["未关闭", "close", "泄漏", "释放", "autocommit", "commit", "rollback"]):
            if "loadrecentauditpaymentids" in text or "loadrecent" in text or "读取" in text:
                return "JDBC_RESOURCE_LIFECYCLE_LOAD"
            if "writebalanceadjustment" in text or "写入" in text or "余额调整" in text:
                return "JDBC_RESOURCE_LIFECYCLE_WRITE"
            return "JDBC_RESOURCE_LIFECYCLE"
    if any(marker in text for marker in ["bean validation", "@valid", "requestbody", "请求体"]) and path.endswith(".java"):
        return "REQUEST_BODY_VALIDATION"
    if any(marker in text for marker in ["debug", "调试", "内部状态"]) and any(marker in text for marker in ["endpoint", "接口", "@getmapping", "@requestmapping"]):
        return "DEBUG_ENDPOINT_EXPOSURE"
    if "threadlocal" in text:
        if "remove" in text or "清理" in text or "泄漏" in text:
            return "THREADLOCAL_LIFECYCLE"
        if "new thread" in text or "后台线程" in text or "跨线程" in text:
            return "THREADLOCAL_CROSS_THREAD"
    if any(marker in text for marker in ["static hashmap", "static arraylist", "静态可变集合", "非线程安全的静态", "spring 单例服务中使用非线程安全"]):
        return "STATIC_MUTABLE_SHARED_STATE"
    if any(marker in text for marker in ["mutabletenantkey", "hashmap key", "map key", "hashcode", "equals", "可变对象", "参与 hash"]):
        if "key" in text or "键" in text or path.endswith("mutabletenantkey.java"):
            return "MUTABLE_HASH_KEY"
    if any(marker in text for marker in ["sha-1", "sha1", "use-of-sha1", "message-digest", "弱摘要"]):
        if any(marker in text for marker in ["signature", "digest", "签名", "摘要", "crypto"]):
            return "WEAK_SIGNATURE_ALGORITHM"
    if path.endswith("refundservice.java") and ("manual_override" in text or ("reason" in text and "绕过" in text)):
        if any(marker in text for marker in ["null", "npe", "空指针", "空值"]) and not any(marker in text for marker in ["绕过", "bypass", "manual_override"]):
            return None
        return "REFUND_REASON_STATE_BYPASS"
    if path.endswith("webhookservice.java") and ("signature" in text or "签名" in text) and any(
        marker in text for marker in ["startswith", "contains", "prefix", "前缀", "伪造", "不可信", "弱"]
    ):
        return "WEBHOOK_SIGNATURE_TRUST"
    if path.endswith("webhookservice.java") and any(marker in text for marker in ["dedupekey", "去重键", "eventid:providertransactionid"]):
        return "WEBHOOK_DEDUPE_KEY_COMPATIBILITY"
    return None


def _business_subcategory(category: str, finding: dict[str, Any]) -> str:
    text = _text_blob(finding)
    path = str(finding.get("file_path") or "").replace("\\", "/").lower()
    if category == "STATE_MACHINE_INTEGRITY":
        if "refund" in text or "退款" in text:
            if any(marker in text for marker in ["cumulative", "prior", "paid amount", "original", "over-refund", "超过", "累计", "原支付", "历史退款"]):
                return "STATE_MACHINE_REFUND_AMOUNT"
            return "STATE_MACHINE_REFUND"
        if "webhook" in text or "eventtype" in text or "事件" in text:
            return "STATE_MACHINE_WEBHOOK"
        if any(marker in text for marker in ["forcecapture", "skiprisk", "bypass", "绕过", "force transition", "强制", "payment", "支付"]):
            return "STATE_MACHINE_PAYMENT"
        if any(marker in text for marker in ["overridestatus", "valueof", "reassignmerchant", "merchantid", "任意", "归属"]):
            return "STATE_MACHINE_PAYMENT"
    if category == "DDD_AGGREGATE_OWNERSHIP":
        return "DDD_AGGREGATE_OWNERSHIP"
    if category in {"UNBOUNDED_QUERY", "UNBOUNDED_DATA_ACCESS"}:
        if any(marker in text for marker in ["requestbody", "@requestbody", "list<", "批量", "bulk", "数组", "请求体", "json array"]):
            return "UNBOUNDED_REQUEST_BODY"
        if any(marker in text for marker in ["cache", "缓存", "static", "ttl", "过期", "容量"]):
            return "UNBOUNDED_CACHE_STATE"
        if any(
            marker in text
            for marker in [
                "like '%",
                "\"%\" +",
                "'%' +",
                "leading wildcard",
                "前导通配",
                "左模糊",
                "like 查询",
                "索引失效",
            ]
        ):
            return "LIKE_LEADING_WILDCARD_INDEX_RISK"
    if category == "ERROR_INFORMATION_LEAK":
        return "ERROR_INFORMATION_LEAK"
    if category == "SENSITIVE_DATA_EXPOSURE":
        if any(marker in text for marker in ["stacktrace", "stack trace", "printstacktrace", "stringwriter", "exception", "异常", "堆栈"]):
            return "ERROR_INFORMATION_LEAK"
        if any(marker in text for marker in ["cardnumber", "cvv", "pan", "pci", "payerdeviceid"]):
            if any(marker in text for marker in ["response", "响应", "dto", "getcard", "getcvv", "返回"]):
                return "SENSITIVE_DATA_RESPONSE"
            if any(marker in text for marker in ["entity", "paymentorder", "字段", "存储", "persist", "column", "列"]):
                return "SENSITIVE_DATA_STORAGE"
        if "log" in text or "日志" in text:
            return "SENSITIVE_DATA_LOGGING"
        if "response" in text or "响应" in text or "dto" in text:
            return "SENSITIVE_DATA_RESPONSE"
        if "entity" in text or "字段" in text or "存储" in text or "persist" in text:
            return "SENSITIVE_DATA_STORAGE"
        if "config" in text or "配置" in text:
            return "SENSITIVE_CONFIG_EXPOSURE"
    if category == "MISSING_TEST_COVERAGE":
        if any(marker in text for marker in ["applicationservice", "状态迁移", "状态流转", "forcetransition", "transactional", "应用服务"]) or "/application/" in path:
            return "MISSING_APP_SERVICE_TEST_COVERAGE"
        if ".yml" in text or ".yaml" in text or "configuration" in text or "配置" in text:
            return "TEST_CONFIG_MASKING"
    return category


def _semantic_dedupe_key(finding: dict[str, Any]) -> tuple[str, str, int]:
    item = normalize_tool_finding(finding)
    root_cause = _root_cause_signature(item)
    return (
        root_cause or _selection_category_key(item),
        str(item.get("file_path") or ""),
        0 if root_cause else line_bucket(item.get("line_start")),
    )


def _merge_finding_metadata(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    covered = set(primary.get("covered_rules") or [])
    covered.update(secondary.get("covered_rules") or [])
    skipped = set(primary.get("skipped_rules") or [])
    skipped.update(secondary.get("skipped_rules") or [])
    primary["covered_rules"] = sorted(str(item) for item in covered if item)
    primary["skipped_rules"] = sorted(str(item) for item in skipped if item)
    primary["confidence"] = min(0.99, max(float(primary.get("confidence") or 0), float(secondary.get("confidence") or 0)) + 0.03)
    return primary


def _stable_sort_key(finding: dict[str, Any]) -> tuple[int, int, float, str, int, str]:
    line = finding.get("line_start")
    verification_flags = {str(flag) for flag in (finding.get("verification_flags") or [])}
    tool_backed = 1 if finding.get("source_tool_observation") or finding.get("tool_name") or "tool_promoted" in verification_flags else 0
    return (
        tool_backed,
        SEVERITY_RANK.get(str(finding.get("severity") or "info"), 0),
        float(finding.get("confidence") or 0),
        str(finding.get("file_path") or ""),
        int(line) if isinstance(line, int) else 0,
        str(finding.get("title") or ""),
    )


CORE_IMPACT_CATEGORIES = {
    "AUTHORIZATION_BYPASS",
    "RISK_CONTROL_BYPASS",
    "WEAK_WEBHOOK_TRUST",
    "SSRF_CALLBACK",
    "WEAK_SIGNATURE_COMPARE",
    "DEBUG_ENDPOINT_EXPOSURE",
    "UNTRUSTED_FORWARDED_HEADER",
    "SQL_INJECTION",
    "MYBATIS_SQL_INJECTION",
    "SENSITIVE_DATA_EXPOSURE",
    "SENSITIVE_DATA_STORAGE",
    "SENSITIVE_DATA_RESPONSE",
    "SENSITIVE_DATA_LOGGING",
    "SENSITIVE_CONFIG_EXPOSURE",
    "SECRET_LEAK",
    "ERROR_INFORMATION_LEAK",
    "CONFIG_SQL_LOGGING",
    "SPRING_ACTUATOR_EXPOSED",
    "STATE_MACHINE_INTEGRITY",
    "STATE_MACHINE_REFUND",
    "STATE_MACHINE_REFUND_AMOUNT",
    "STATE_MACHINE_WEBHOOK",
    "STATE_MACHINE_PAYMENT",
    "BIGDECIMAL_PRECISION",
    "THREADLOCAL_LEAK",
    "THREAD_UNSAFE_SHARED_STATE",
    "DB_CONNECTION_STATE_LEAK",
    "TRANSACTION_PROXY_INVALID",
    "SPRING_TRANSACTION",
    "DB_TX_005",
    "DDD_AGGREGATE_OWNERSHIP",
    "UNBOUNDED_QUERY",
    "UNBOUNDED_RESULT_MEMORY",
    "UNBOUNDED_REQUEST_BODY",
    "UNBOUNDED_CACHE_STATE",
    "LIKE_LEADING_WILDCARD_INDEX_RISK",
    "NULL_SAFETY",
    "BROAD_EXCEPTION",
    "MISSING_APP_SERVICE_TEST_COVERAGE",
}


def _added_line_index(files: list[Any]) -> dict[str, set[int]]:
    index: dict[str, set[int]] = {}
    for changed in files or []:
        file_path = str(getattr(changed, "filename", "") or "")
        if not file_path:
            continue
        lines = {int(line_no) for line_no, _ in extract_added_lines(str(getattr(changed, "patch", "") or "")) if line_no is not None}
        index[file_path] = lines
    return index


def _added_line_text_index(files: list[Any]) -> dict[str, dict[int, str]]:
    index: dict[str, dict[int, str]] = {}
    for changed in files or []:
        file_path = str(getattr(changed, "filename", "") or "")
        if not file_path:
            continue
        index[file_path] = {
            int(line_no): str(text or "")
            for line_no, text in extract_added_lines(str(getattr(changed, "patch", "") or ""))
            if line_no is not None
        }
    return index


def _nearest_added_line(file_path: str, line: int, added_lines: set[int], *, max_distance: int = 5) -> int | None:
    if not added_lines:
        return None
    candidate = min(added_lines, key=lambda value: (abs(value - line), value))
    if abs(candidate - line) <= max_distance:
        return candidate
    return None


def _best_semantic_added_line(
    finding: dict[str, Any],
    file_path: str,
    line: int,
    added_lines: set[int],
    added_text: dict[str, dict[int, str]],
    *,
    max_distance: int = 20,
) -> int | None:
    if not added_lines:
        return None
    text_by_line = added_text.get(file_path) or {}
    for candidate in sorted(added_lines, key=lambda value: (abs(value - line), value)):
        if abs(candidate - line) > max_distance:
            continue
        if _can_reanchor_to_added_line(finding, text_by_line.get(candidate, "")):
            return candidate
    return None


def _significant_tokens(value: str) -> set[str]:
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", value or ""))
    stop_words = {
        "public",
        "private",
        "protected",
        "return",
        "class",
        "void",
        "this",
        "String",
        "java",
        "true",
        "false",
        "null",
        "status",
        "line",
    }
    return {token.lower() for token in tokens if token not in stop_words}


def _can_reanchor_to_added_line(finding: dict[str, Any], added_line_text: str) -> bool:
    finding_tokens = _significant_tokens(_text_blob(finding))
    line_tokens = _significant_tokens(added_line_text)
    if not finding_tokens or not line_tokens:
        return False
    overlap = finding_tokens & line_tokens
    if len(overlap) >= 2:
        return True
    category = _selection_category_key(finding)
    lowered_line = added_line_text.lower()
    if category in {"SQL_INJECTION", "MYBATIS_SQL_INJECTION"}:
        return any(marker in lowered_line for marker in ["sql", "query", "jdbc", "execute", "statement"])
    if category in {"WEAK_WEBHOOK_TRUST", "STATE_MACHINE_WEBHOOK"}:
        return any(marker in lowered_line for marker in ["signature", "event", "webhook", "dedupe"])
    if category == "SENSITIVE_DATA_LOGGING":
        return any(marker in lowered_line for marker in ["log", "rawpayload", "signature", "token", "payload", "audit", "write"])
    if category in {"SENSITIVE_DATA_STORAGE", "SENSITIVE_DATA_RESPONSE", "SENSITIVE_DATA_EXPOSURE"}:
        return any(marker in lowered_line for marker in ["card", "cvv", "pan", "paymentresponse", "response", "dto", "payerdevice"])
    if category == "STATE_MACHINE_PAYMENT":
        return any(marker in lowered_line for marker in ["forcecapture", "skiprisk", "status", "forcetransition", "valueof", "bypass", "force"])
    if category in {"STATE_MACHINE_REFUND"}:
        return any(marker in lowered_line for marker in ["manual_override", "reason", "refund", "refunded"])
    if category in {"DDD_AGGREGATE_OWNERSHIP"}:
        return any(marker in lowered_line for marker in ["reassignmerchant", "merchantid", "ownership", "aggregate"])
    if category in {"IDEMPOTENCY_GUARD"}:
        return any(marker in lowered_line for marker in ["dedupe", "idempot", "eventid", "providertransactionid"])
    if category == "LIKE_LEADING_WILDCARD_INDEX_RISK":
        return any(marker in lowered_line for marker in ["like", "%", "query", "search", "sql", "merchant", "keyword"])
    if category in {"SSRF_CALLBACK"}:
        return any(marker in lowered_line for marker in ["callback", "resttemplate", "postforentity", "url"])
    return False


def _diff_anchor_result(finding: dict[str, Any], added_lines: dict[str, set[int]], added_text: dict[str, dict[int, str]]) -> tuple[dict[str, Any] | None, str | None]:
    file_path = str(finding.get("file_path") or "")
    line = _as_int(finding.get("line_start"))
    if not file_path or line is None:
        return finding, None
    file_added_lines = added_lines.get(file_path)
    if file_added_lines is None:
        return finding, None
    if not file_added_lines:
        return None, "not_on_added_or_modified_line"
    if line in file_added_lines:
        return finding, None
    nearest = _best_semantic_added_line(finding, file_path, line, file_added_lines, added_text)
    if nearest is None:
        nearest = _nearest_added_line(file_path, line, file_added_lines)
    if nearest is None:
        return None, "not_on_added_or_modified_line"
    nearest_text = (added_text.get(file_path) or {}).get(nearest, "")
    if not _can_reanchor_to_added_line(finding, nearest_text):
        return None, "context_line_not_semantically_tied_to_added_line"
    anchored = dict(finding)
    anchored["line_start"] = nearest
    anchored["line_end"] = nearest
    anchored["verification_flags"] = [*(anchored.get("verification_flags") or []), "diff_anchor_relocated"]
    anchored["quality_trace"] = {
        **(anchored.get("quality_trace") if isinstance(anchored.get("quality_trace"), dict) else {}),
        "original_line_start": line,
        "diff_anchor_line": nearest,
        "diff_anchor_reason": "semantic_nearby_added_line",
    }
    return anchored, None


def filter_to_diff_introduced_findings(
    findings: list[dict[str, Any]],
    files: list[Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    added_lines = _added_line_index(files)
    added_text = _added_line_text_index(files)
    if not added_lines:
        return findings, []
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for finding in findings:
        anchored, reason = _diff_anchor_result(finding, added_lines, added_text)
        if anchored is None:
            rejected.append({**finding, "rejected_reasons": [reason or "not_introduced_by_diff"]})
            continue
        kept.append(anchored)
    return kept, rejected


def filter_tool_observations_to_added_lines(
    tool_observations: list[dict[str, Any]],
    files: list[Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    added_lines = _added_line_index(files)
    added_text = _added_line_text_index(files)
    if not added_lines:
        return tool_observations, []
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for observation in tool_observations:
        file_path = str(observation.get("file_path") or "")
        line = _as_int(observation.get("line_start"))
        if not file_path or line is None or file_path not in added_lines:
            kept.append(observation)
            continue
        if line in added_lines[file_path]:
            kept.append(observation)
            continue
        rule_id = str(observation.get("rule_id") or "")
        fake_finding = normalize_tool_finding(
            {
                "agent_id": _agent_for_rule(CATEGORY_PRIMARY_RULE.get(normalized_rule_category(rule_id, observation.get("message")), rule_id)),
                "file_path": file_path,
                "line_start": line,
                "line_end": observation.get("line_end"),
                "title": observation.get("message") or rule_id,
                "problem_description": observation.get("message") or rule_id,
                "evidence": observation.get("message") or rule_id,
                "covered_rules": [CATEGORY_PRIMARY_RULE.get(normalized_rule_category(rule_id, observation.get("message")), rule_id)],
                "tool_rule_id": rule_id,
            }
        )
        relocated = _best_semantic_added_line(fake_finding, file_path, line, added_lines[file_path], added_text)
        if relocated is not None:
            kept.append(
                {
                    **observation,
                    "line_start": relocated,
                    "line_end": relocated,
                    "original_line_start": line,
                    "adoption_state": observation.get("adoption_state") or "candidate_reanchored",
                }
            )
            continue
        rejected.append({**observation, "rejected_reasons": ["tool_observation_not_on_added_line"]})
    return kept, rejected

AUXILIARY_TITLE_MARKERS = [
    "缺少测试",
    "未覆盖",
    "测试覆盖",
    "回归测试",
    "契约测试",
    "领域事件",
    "事件抽象",
    "缺失领域事件",
]


def _category_for_priority(finding: dict[str, Any]) -> str:
    item = normalize_tool_finding(finding)
    for rule in item.get("covered_rules") or []:
        category_from_rule = normalized_rule_category(str(rule), item.get("title"))
        if category_from_rule and category_from_rule != "GENERAL":
            return category_from_rule
    category = str(item.get("normalized_rule_category") or "")
    if category and category != "GENERAL":
        return category
    return normalized_rule_category(_primary_rule_key(item), item.get("title"))


def _path_relevance_score(finding: dict[str, Any], category: str) -> int:
    path = str(finding.get("file_path") or "").replace("\\", "/").lower()
    text = _text_blob(finding)
    if category == "MISSING_APP_SERVICE_TEST_COVERAGE":
        if "/application/" in path or "applicationservice" in text:
            return 8
        if "/service/" in path:
            return 6
    if category == "LIKE_LEADING_WILDCARD_INDEX_RISK":
        if "/repository/" in path or "/mapper/" in path:
            return 8
        if "/application/" in path or "/service/" in path:
            return 7
    if category == "STATE_MACHINE_INTEGRITY":
        if "/service/" in path or "/application/" in path:
            return 7
        if "/api/" in path or "/controller" in path:
            return 5
        if "/domain/" in path:
            return 3
    if category in {"STATE_MACHINE_PAYMENT", "DDD_AGGREGATE_OWNERSHIP"}:
        if "/domain/" in path or "/application/" in path:
            return 8
        if "/service/" in path:
            return 7
    if category in {"SPRING_VALIDATION", "AUTHORIZATION_BYPASS", "RISK_CONTROL_BYPASS", "WEAK_WEBHOOK_TRUST", "SSRF_CALLBACK"}:
        if "/api/" in path or "/controller" in path:
            return 7
        if "/service/" in path:
            return 6
    if category in {"BIGDECIMAL_PRECISION", "NULL_SAFETY", "BROAD_EXCEPTION", "SPRING_TRANSACTION"}:
        if "/service/" in path or "/api/" in path:
            return 6
        if "/domain/" in path:
            return 4
    if path.endswith((".yml", ".yaml", ".properties")):
        return 6 if category in {"CONFIG_SQL_LOGGING", "SPRING_ACTUATOR_EXPOSED", "ERROR_INFORMATION_LEAK", "MISSING_TEST_COVERAGE"} else 2
    if "/test/" in path or "src/test/" in path:
        return 5 if category == "MISSING_TEST_COVERAGE" and ("skip" in text or "mask" in text or "配置" in text) else 1
    if "/service/" in path:
        return 5
    if "/api/" in path or "/controller" in path:
        return 4
    if "/domain/" in path:
        return 3
    return 2


def _auxiliary_penalty(finding: dict[str, Any], category: str) -> int:
    text = _text_blob(finding)
    covered = {str(rule) for rule in (finding.get("covered_rules") or [])}
    penalty = 0
    if category == "MISSING_APP_SERVICE_TEST_COVERAGE":
        return 0
    if category == "MISSING_TEST_COVERAGE" and not _is_tool_backed_finding(finding):
        penalty += 5
    if any(rule.startswith("TEST-") for rule in covered) and not _is_tool_backed_finding(finding):
        penalty += 3
    if any(marker in text for marker in AUXILIARY_TITLE_MARKERS) and not _is_tool_backed_finding(finding):
        penalty += 2
    if ("ddd-event" in text or "领域事件" in text or "事件抽象" in text) and not _is_tool_backed_finding(finding):
        penalty += 3
    return penalty


def _category_impact_score(finding: dict[str, Any], category: str) -> int:
    covered = {str(rule) for rule in (finding.get("covered_rules") or [])}
    score = 0
    if category in CORE_IMPACT_CATEGORIES:
        score += 8
    if category in {"STATE_MACHINE_REFUND", "STATE_MACHINE_REFUND_AMOUNT", "STATE_MACHINE_WEBHOOK", "STATE_MACHINE_PAYMENT"}:
        score += 8
    if category == "DDD_AGGREGATE_OWNERSHIP":
        score += 8
    if category in {"LIKE_LEADING_WILDCARD_INDEX_RISK", "MISSING_APP_SERVICE_TEST_COVERAGE"}:
        score += 6
    if category in {"UNBOUNDED_REQUEST_BODY", "UNBOUNDED_CACHE_STATE"}:
        score += 7
    if category.startswith("SENSITIVE_DATA_"):
        score += 5
    if category.startswith("SEC_") or any(rule.startswith("SEC-") for rule in covered):
        score += 4
    if category.startswith("DB_") or any(rule.startswith("DB-") for rule in covered):
        score += 3
    if any(rule.startswith(("BE-", "CODE-", "ALI-", "HW-")) for rule in covered):
        score += 2
    if category in {"MISSING_TEST_COVERAGE"}:
        score -= 4
    if not covered and not finding.get("tool_rule_id") and not finding.get("rule_id"):
        score -= 2
    return score


def _is_core_impact_finding(finding: dict[str, Any]) -> bool:
    category = _selection_category_key(finding)
    return category in CORE_IMPACT_CATEGORIES or _category_impact_score(finding, category) >= 8


def _is_secondary_advisory_finding(finding: dict[str, Any]) -> bool:
    if _is_tool_backed_finding(finding):
        return False
    item = normalize_tool_finding(finding)
    covered = {str(rule) for rule in (item.get("covered_rules") or [])}
    category = _selection_category_key(item)
    text = _text_blob(item)
    confidence = float(item.get("confidence") or 0)
    if any(rule.startswith("TEST-") for rule in covered):
        return True
    if category in {"DDD_AGGREGATE_OWNERSHIP", "DDD_APP_003", "DDD_REPO_004"}:
        return True
    if any(rule in {"DDD-APP-003", "DDD-REPO-004"} for rule in covered):
        return True
    if category == "DDD_VO_002" and "mutabletenantkey" not in text and "hash" not in text and "key" not in text:
        return True
    if category in {"SPRING_TRANSACTION"} and confidence <= 0.76:
        return True
    return False


def _is_auxiliary_finding(finding: dict[str, Any]) -> bool:
    category = _selection_category_key(finding)
    covered = {str(rule) for rule in (finding.get("covered_rules") or [])}
    text = _text_blob(finding)
    if category == "MISSING_APP_SERVICE_TEST_COVERAGE":
        return False
    if category == "MISSING_TEST_COVERAGE":
        return True
    if category in {"IDEMPOTENCY_GUARD", "BROAD_EXCEPTION"} and not _is_tool_backed_finding(finding):
        return True
    if any(rule.startswith("TEST-") for rule in covered) and not _is_tool_backed_finding(finding):
        return True
    return any(marker in text for marker in AUXILIARY_TITLE_MARKERS) and not _is_tool_backed_finding(finding)


def _evidence_specificity_score(finding: dict[str, Any]) -> int:
    score = 0
    if finding.get("file_path"):
        score += 2
    if _as_int(finding.get("line_start")) is not None:
        score += 2
    if finding.get("covered_rules"):
        score += 2
    if _is_tool_backed_finding(finding):
        score += 3
    evidence = str(finding.get("evidence") or finding.get("problem_description") or "")
    if len(evidence.strip()) >= 80:
        score += 1
    if "Evidence:" in evidence or "证据" in evidence or "line " in evidence:
        score += 1
    return score


def _priority_sort_key(finding: dict[str, Any]) -> tuple[int, int, int, int, int, float, tuple[int, int, float, str, int, str]]:
    normalized = normalize_tool_finding(finding)
    category = _category_for_priority(normalized)
    concrete_category = _business_subcategory(_semantic_category_group(category), normalized)
    return (
        _category_impact_score(normalized, concrete_category),
        _path_relevance_score(normalized, concrete_category),
        _evidence_specificity_score(normalized),
        -_auxiliary_penalty(normalized, concrete_category),
        SEVERITY_RANK.get(str(normalized.get("severity") or "info"), 0),
        float(normalized.get("confidence") or 0),
        _stable_sort_key(normalized),
    )


def _is_tool_backed_finding(finding: dict[str, Any]) -> bool:
    verification_flags = {str(flag) for flag in (finding.get("verification_flags") or [])}
    return bool(finding.get("source_tool_observation") or finding.get("tool_name") or "tool_promoted" in verification_flags)


def _preserve_static_tool_finding(finding: dict[str, Any]) -> bool:
    if not _is_tool_backed_finding(finding):
        return False
    severity = str(finding.get("severity") or "").lower()
    if severity not in SELECTABLE_SEVERITIES:
        return False
    try:
        confidence = float(finding.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0
    return confidence >= 0.76 and bool(finding.get("file_path"))


def _selection_category_key(finding: dict[str, Any]) -> str:
    item = normalize_tool_finding(finding)
    for rule in item.get("covered_rules") or []:
        normalized_from_rule = normalized_rule_category(str(rule), item.get("title"))
        if normalized_from_rule and normalized_from_rule != "GENERAL":
            return _business_subcategory(_semantic_category_group(normalized_from_rule), item)
    category = str(item.get("normalized_rule_category") or "")
    if category and category != "GENERAL":
        return _business_subcategory(_semantic_category_group(category), item)
    rule_key = _primary_rule_key(item)
    if rule_key:
        normalized = normalized_rule_category(rule_key, item.get("title"))
        return _business_subcategory(_semantic_category_group(normalized), item)
    return str(item.get("title") or "GENERAL")[:80]


def _normalize_for_judging(finding: dict[str, Any]) -> dict[str, Any]:
    item = normalize_tool_finding(finding)
    item["semantic_category"] = _selection_category_key(item)
    return item


def _select_with_category_coverage(ordered: list[dict[str, Any]], max_findings: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    selected_hashes: set[str] = set()
    covered_categories: set[str] = set()

    def add_selected(item: dict[str, Any]) -> None:
        selected.append(item)
        selected_hashes.add(str(item.get("dedupe_hash") or ""))
        covered_categories.add(_selection_category_key(item))

    for item in ordered:
        if not _preserve_static_tool_finding(item):
            continue
        category = _selection_category_key(item)
        if category in covered_categories:
            continue
        add_selected(item)
        if len(selected) >= max_findings:
            overflow = [candidate for candidate in ordered if str(candidate.get("dedupe_hash") or "") not in selected_hashes]
            rejected.extend({**candidate, "rejected_reasons": ["max_findings_exceeded"]} for candidate in overflow)
            return selected, rejected

    for item in ordered:
        item_hash = str(item.get("dedupe_hash") or "")
        if item_hash in selected_hashes:
            continue
        category = _selection_category_key(item)
        if category in covered_categories:
            continue
        add_selected(item)
        if len(selected) >= max_findings:
            overflow = [candidate for candidate in ordered if str(candidate.get("dedupe_hash") or "") not in selected_hashes]
            rejected.extend({**candidate, "rejected_reasons": ["max_findings_exceeded"]} for candidate in overflow)
            return selected, rejected

    for item in ordered:
        item_hash = str(item.get("dedupe_hash") or "")
        if item_hash in selected_hashes:
            continue
        selected.append(item)
        selected_hashes.add(item_hash)
        if len(selected) >= max_findings:
            break

    overflow = [candidate for candidate in ordered if str(candidate.get("dedupe_hash") or "") not in selected_hashes]
    rejected.extend({**candidate, "rejected_reasons": ["max_findings_exceeded"]} for candidate in overflow)
    return selected, rejected


def _line_proximity_key(finding: dict[str, Any]) -> tuple[str, int]:
    return (str(finding.get("file_path") or ""), line_bucket(_as_int(finding.get("line_start"))))


def _near_selected_core_finding(finding: dict[str, Any], selected: list[dict[str, Any]]) -> bool:
    path = str(finding.get("file_path") or "")
    line = _as_int(finding.get("line_start"))
    if not path or line is None:
        return False
    for item in selected:
        if not _is_core_impact_finding(item):
            continue
        if str(item.get("file_path") or "") != path:
            continue
        other_line = _as_int(item.get("line_start"))
        if other_line is None:
            continue
        if abs(other_line - line) <= 8:
            return True
    return False


def _drop_auxiliary_overlaps(selected: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in selected:
        if _is_auxiliary_finding(item) and _near_selected_core_finding(item, [*kept, *selected]):
            rejected.append({**item, "rejected_reasons": ["auxiliary_overlap_core_issue"]})
            continue
        kept.append(item)
    return kept, rejected


def _fill_after_auxiliary_drop(
    selected: list[dict[str, Any]],
    ordered: list[dict[str, Any]],
    max_findings: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected_hashes = {str(item.get("dedupe_hash") or "") for item in selected}
    rejected: list[dict[str, Any]] = []
    for candidate in ordered:
        if len(selected) >= max_findings:
            break
        candidate_hash = str(candidate.get("dedupe_hash") or "")
        if candidate_hash in selected_hashes:
            continue
        if _is_auxiliary_finding(candidate) and _near_selected_core_finding(candidate, selected):
            rejected.append({**candidate, "rejected_reasons": ["auxiliary_overlap_core_issue"]})
            selected_hashes.add(candidate_hash)
            continue
        selected.append(candidate)
        selected_hashes.add(candidate_hash)
    return selected, rejected


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _agent_for_rule(rule_id: str) -> str:
    if rule_id in AGENT_BY_RULE:
        return AGENT_BY_RULE[rule_id]
    for prefix, agent_id in AGENT_BY_RULE_PREFIX.items():
        if rule_id.startswith(prefix):
            return agent_id
    return "coding_agent"


def _is_placeholder_suggested_code(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    lowered = text.lower()
    placeholder_markers = [
        "根据当前文件上下文",
        "按以下方向调整",
        "在命中行附近按工具规则修改实现",
        "重新运行对应静态工具确认",
        "todo",
        "fixme",
    ]
    return any(marker.lower() in lowered for marker in placeholder_markers)


def ensure_actionable_suggested_code(finding: dict[str, Any]) -> dict[str, Any]:
    item = dict(finding)
    if not _is_placeholder_suggested_code(item.get("suggested_code")):
        return item
    for rule in item.get("covered_rules") or []:
        remediation = RULE_REMEDIATION.get(str(rule))
        if remediation and not _is_placeholder_suggested_code(remediation.get("suggested_code")):
            item["suggested_code"] = remediation["suggested_code"]
            item["recommendation"] = remediation.get("recommendation") or item.get("recommendation")
            item["verification_flags"] = [*(item.get("verification_flags") or []), "suggested_code_from_rule_template"]
            return item
    item["selected"] = 0
    item["verification_flags"] = [*(item.get("verification_flags") or []), "invalid_suggested_code"]
    return item


def dependency_suggested_code_from_observation(observation: dict[str, Any]) -> str | None:
    message = str(observation.get("message") or "")
    match = re.search(
        r"(?P<group>[A-Za-z0-9_.-]+):(?P<artifact>[A-Za-z0-9_.-]+):(?P<version>[A-Za-z0-9_.-]+)(?:\s+fixed=(?P<fixed>[A-Za-z0-9_.,\s-]+))?",
        message,
    )
    if not match:
        return None
    fixed = (match.group("fixed") or "").split(",")[0].strip() or "fixed.version"
    return f'''<dependency>
  <groupId>{match.group("group")}</groupId>
  <artifactId>{match.group("artifact")}</artifactId>
  <version>{fixed}</version>
</dependency>'''


def remediation_for_observation(rule_id: str, observation: dict[str, Any]) -> dict[str, str]:
    remediation = dict(RULE_REMEDIATION.get(rule_id, {}))
    if rule_id == "DEP-CVE-001":
        suggested_code = dependency_suggested_code_from_observation(observation)
        if suggested_code:
            remediation["suggested_code"] = suggested_code
    return remediation


def _drop_without_tool_support(finding: dict[str, Any], source_observations: list[dict[str, Any]]) -> bool:
    category = _selection_category_key(finding)
    if category in {"REDIS_MISSING_TTL", "REDIS_DANGEROUS_COMMAND"}:
        source_categories = {
            normalized_rule_category(str(item.get("rule_id") or ""), item.get("message"))
            for item in source_observations
            if item.get("rule_id") or item.get("message")
        }
        implementation_text = " ".join(
            str(finding.get(key) or "")
            for key in ["title", "problem_description", "evidence", "file_path"]
        ).lower()
        has_redis_evidence = any(category.startswith("REDIS_") for category in source_categories) or any(
            marker in implementation_text
            for marker in [
                "redistemplate",
                "stringredistemplate",
                "redisconnection",
                "redisclient",
                "redisrepository",
                "redis.",
                ".opsfor",
                "opsforvalue",
                "opsforhash",
            ]
        )
        if not has_redis_evidence:
            return True
    return False


def _canonical_tool_rule_id(observation: dict[str, Any]) -> str:
    raw_rule = canonical_rule_id(observation.get("rule_id"))
    tool_name = str(observation.get("tool_name") or "").strip().lower()
    if raw_rule in PROMOTABLE_TOOL_RULES:
        return raw_rule
    if raw_rule in PROMOTABLE_EXTERNAL_TOOL_RULES:
        return PROMOTABLE_EXTERNAL_TOOL_RULES[raw_rule]
    category = normalized_rule_category(raw_rule, observation.get("message"))
    primary = CATEGORY_PRIMARY_RULE.get(category, "")
    if primary in PROMOTABLE_TOOL_RULES:
        return primary
    if tool_name == "pmd" and raw_rule == "CloseResource":
        return "CODE-RESOURCE-005"
    return ""


def _promotable_tool_observation(observation: dict[str, Any]) -> bool:
    rule_id = _canonical_tool_rule_id(observation)
    if rule_id not in PROMOTABLE_TOOL_RULES:
        return False
    tool_name = str(observation.get("tool_name") or "").strip().lower()
    confidence = float(observation.get("confidence") or 0)
    has_location = bool(observation.get("file_path")) and _as_int(observation.get("line_start")) is not None
    if tool_name == "java_web_static":
        return confidence >= 0.78 and has_location
    if tool_name == "pmd":
        return rule_id in {"CODE-EXC-003", "CODE-RESOURCE-005"} and confidence >= 0.75
    if tool_name == "semgrep":
        return rule_id in {
            "BE-API-001",
            "BE-IDEMP-004",
            "CODE-NULL-001",
            "CODE-STATE-004",
            "DB-DDL-001",
            "DDD-AGG-001",
            "DDD-VO-002",
            "ALI-BIGDECIMAL-001",
            "PERF-LIKE-002",
            "PERF-QUERY-001",
            "REDIS-CMD-003",
            "REDIS-TTL-002",
            "SEC-AUTHZ-002",
            "SEC-CRYPTO-010",
            "SEC-DEBUG-011",
            "SEC-CONFIG-007",
            "SEC-INJECT-003",
            "SEC-RISK-006",
            "SEC-SECRET-004",
            "SEC-SECRET-004:ERROR_RESPONSE",
            "SEC-SSRF-009",
            "SEC-WEBHOOK-008",
            "TEST-COVER-001",
            "ALI-CONCURRENCY-001",
            "ALI-CONCURRENCY-002",
            "ALI-CONCURRENCY-003",
            "CODE-RESOURCE-005",
            "HW-TX-001",
        } and confidence >= 0.76
    if tool_name in {"trivy", "osv"}:
        return rule_id == "DEP-CVE-001" and confidence >= 0.78 and bool(observation.get("file_path"))
    threshold = OSS_TOOL_PROMOTION_THRESHOLDS.get(tool_name)
    if threshold is None:
        return False
    if tool_name in {"dependency-check", "trivy", "osv"}:
        return rule_id == "DEP-CVE-001" and confidence >= threshold and bool(observation.get("file_path"))
    return confidence >= threshold and has_location


def _tool_candidate_hash(rule_id: str, observation: dict[str, Any]) -> str:
    return sha1(
        "|".join(
            [
                "tool-promoted",
                rule_id,
                str(observation.get("file_path") or ""),
                str(line_bucket(_as_int(observation.get("line_start")))),
                str(observation.get("message") or "")[:160],
            ]
        )
    )


def _tool_observation_group_key(rule_id: str, observation: dict[str, Any]) -> tuple[str, str, str, str]:
    raw_rule = canonical_rule_id(observation.get("rule_id"))
    artifact = str(observation.get("raw_artifact_id") or "")
    return (
        rule_id,
        raw_rule,
        str(observation.get("file_path") or ""),
        artifact,
    )


def _severity_rank_value(observation: dict[str, Any]) -> int:
    return SEVERITY_RANK.get(str(observation.get("severity") or "info").lower(), 0)


def _best_tool_observation(observations: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(
        observations,
        key=lambda item: (
            _severity_rank_value(item),
            float(item.get("confidence") or 0),
            -(_as_int(item.get("line_start")) or 10**9),
        ),
        reverse=True,
    )[0]


def _format_observation_evidence(observations: list[dict[str, Any]], *, limit: int = 8) -> str:
    parts: list[str] = []
    for observation in sorted(observations, key=lambda item: (_as_int(item.get("line_start")) or 10**9, str(item.get("message") or "")))[:limit]:
        line = _as_int(observation.get("line_start"))
        prefix = f"line {line}: " if line is not None else ""
        message = str(observation.get("message") or "").strip()
        if message:
            parts.append(f"{prefix}{message}")
    return "\n".join(parts)


def promote_tool_observations(
    tool_observations: list[dict[str, Any]],
    existing_findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_keys = {_dedupe_key(item) for item in existing_findings}
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    group_rule: dict[tuple[str, str, str, str], str] = {}
    for observation in tool_observations:
        if not _promotable_tool_observation(observation):
            continue
        rule_id = _canonical_tool_rule_id(observation)
        key = _tool_observation_group_key(rule_id, observation)
        grouped.setdefault(key, []).append(observation)
        group_rule[key] = rule_id

    promoted: list[dict[str, Any]] = []
    for group_key, observations in grouped.items():
        rule_id = group_rule[group_key]
        observation = _best_tool_observation(observations)
        line_start = _as_int(observation.get("line_start"))
        line_values = [_as_int(item.get("line_start")) for item in observations]
        line_values = [value for value in line_values if value is not None]
        line_end = max(line_values) if line_values else (_as_int(observation.get("line_end")) or line_start)
        remediation = remediation_for_observation(rule_id, observation)
        title = remediation.get("title") or str(observation.get("message") or rule_id).strip()[:80] or rule_id
        evidence = _format_observation_evidence(observations) or observation.get("message") or title
        candidate = normalize_tool_finding(
            {
                "severity": observation.get("severity") or "medium",
                "confidence": max(max(float(item.get("confidence") or 0.8) for item in observations), 0.8),
                "agent_id": _agent_for_rule(rule_id),
                "file_path": observation.get("file_path"),
                "line_start": line_start,
                "line_end": line_end,
                "title": title,
                "problem_description": evidence,
                "recommendation": remediation.get("recommendation")
                or "按命中的项目代码规范修复该问题，并补充对应测试或回归验证。",
                "suggested_code": remediation.get("suggested_code")
                or f"// {rule_id} 建议修改示例\n// 按命中规则在上述位置修改实现，并补充对应回归测试。",
                "evidence": evidence,
                "tool_name": observation.get("tool_name"),
                "tool_rule_id": rule_id,
                "raw_artifact_id": observation.get("raw_artifact_id"),
                "covered_rules": [rule_id],
                "skipped_rules": [],
                "judge_adjustment": "promoted_from_tool_observation",
                "verification_flags": ["tool_promoted"],
                "source_tool_observation": observation,
            }
        )
        candidate["dedupe_hash"] = sha1(
            "|".join(
                [
                    "tool-promoted",
                    *group_key,
                    str(line_bucket(line_start)),
                    evidence[:240],
                ]
            )
        )
        key = _dedupe_key(candidate)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        promoted.append(candidate)
    return promoted


def apply_debate_verdicts(findings: list[dict[str, Any]], debate_results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    verdict_by_hash: dict[str, dict[str, Any]] = {}
    for result in debate_results:
        if not isinstance(result, dict):
            continue
        for finding_hash in result.get("finding_hashes") or []:
            if finding_hash:
                verdict_by_hash[str(finding_hash)] = result

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for finding in findings:
        item = dict(finding)
        verdict = verdict_by_hash.get(str(item.get("dedupe_hash") or ""))
        if not verdict:
            accepted.append(item)
            continue
        decision = str(verdict.get("verdict") or "keep")
        if decision == "drop":
            rejected.append({**item, "rejected_reasons": ["debate_drop"], "debate_verdict": verdict})
            continue
        calibrated_confidence = verdict.get("calibrated_confidence")
        if calibrated_confidence is not None:
            try:
                item["confidence"] = max(0.0, min(0.99, float(calibrated_confidence)))
            except (TypeError, ValueError):
                pass
        calibrated_severity = str(verdict.get("calibrated_severity") or "").lower()
        if decision == "downgrade" and calibrated_severity in SEVERITY_RANK:
            item["severity"] = calibrated_severity
            item["judge_adjustment"] = "debate_downgraded"
        elif decision == "keep":
            item["judge_adjustment"] = "debate_keep"
        item["debate_verdict"] = verdict
        accepted.append(item)
    return accepted, rejected


def _rule_categories_for_finding(finding: dict[str, Any]) -> set[str]:
    rules = set(str(item) for item in (finding.get("covered_rules") or []) if item)
    rules.add(str(finding.get("tool_rule_id") or finding.get("rule_id") or ""))
    rules.add(str(finding.get("normalized_rule_category") or ""))
    return {normalized_rule_category(rule, finding.get("title")) for rule in rules if rule}


def _observation_trace_item(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool_name": observation.get("tool_name"),
        "rule_id": observation.get("rule_id"),
        "severity": observation.get("severity"),
        "confidence": observation.get("confidence"),
        "file_path": observation.get("file_path"),
        "line_start": observation.get("line_start"),
        "line_end": observation.get("line_end"),
        "message": observation.get("message"),
        "raw_artifact_id": observation.get("raw_artifact_id"),
        "adoption_state": observation.get("adoption_state"),
    }


def match_tool_observations_for_finding(
    finding: dict[str, Any],
    tool_observations: list[dict[str, Any]],
    *,
    line_tolerance: int = 3,
) -> list[dict[str, Any]]:
    normalized = normalize_tool_finding(finding)
    file_path = str(normalized.get("file_path") or "")
    line_start = _as_int(normalized.get("line_start"))
    finding_categories = _rule_categories_for_finding(normalized)
    finding_rules = set(str(item) for item in (normalized.get("covered_rules") or []) if item)
    finding_rules.add(str(normalized.get("tool_rule_id") or ""))

    matched: list[tuple[int, dict[str, Any]]] = []
    for observation in tool_observations:
        if str(observation.get("file_path") or "") != file_path:
            continue
        obs_line = _as_int(observation.get("line_start"))
        same_line = line_start is None or obs_line is None or abs(obs_line - line_start) <= line_tolerance
        obs_rule = str(observation.get("rule_id") or "")
        obs_category = normalized_rule_category(obs_rule, observation.get("message"))
        same_rule = obs_rule in finding_rules or obs_category in finding_categories
        if not same_rule:
            continue
        if not same_line:
            continue
        score = 0
        if same_line:
            score += 3
        if same_rule:
            score += 4
        if str(observation.get("tool_name") or "") == str(normalized.get("tool_name") or ""):
            score += 1
        matched.append((score, _observation_trace_item(observation)))
    matched.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in matched[:8]]


def reconcile_rules_with_tool_observations(
    finding: dict[str, Any],
    source_observations: list[dict[str, Any]],
) -> dict[str, Any]:
    if not source_observations:
        return finding
    source_categories = {
        normalized_rule_category(str(item.get("rule_id") or ""), item.get("message"))
        for item in source_observations
        if item.get("rule_id") or item.get("message")
    }
    if not source_categories:
        return finding

    covered_rules = [str(rule) for rule in (finding.get("covered_rules") or []) if rule]
    if not covered_rules:
        return finding
    filtered_rules = [
        rule
        for rule in covered_rules
        if normalized_rule_category(rule, finding.get("title")) in source_categories
    ]
    if not filtered_rules or filtered_rules == covered_rules:
        return finding

    item = dict(finding)
    item["covered_rules"] = filtered_rules
    item["rule_reconciliation"] = {
        "removed_rules": [rule for rule in covered_rules if rule not in filtered_rules],
        "source_categories": sorted(source_categories),
    }
    return normalize_tool_finding(item)


def build_quality_trace(finding: dict[str, Any], source_observations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "agent_id": finding.get("agent_id"),
        "agent_display_name": finding.get("agent_display_name") or finding.get("agent_id"),
        "severity": finding.get("severity"),
        "confidence": finding.get("confidence"),
        "location": {
            "file_path": finding.get("file_path"),
            "line_start": finding.get("line_start"),
            "line_end": finding.get("line_end"),
        },
        "dedupe_hash": finding.get("dedupe_hash"),
        "covered_rules": finding.get("covered_rules") or [],
        "skipped_rules": finding.get("skipped_rules") or [],
        "rule_reconciliation": finding.get("rule_reconciliation"),
        "verification": {
            "flags": finding.get("verification_flags") or [],
            "evidence_match_score": finding.get("evidence_match_score"),
        },
        "judge": {
            "selected": bool(finding.get("selected")),
            "adjustment": finding.get("judge_adjustment"),
        },
        "calibration": finding.get("calibration") or {},
        "debate": finding.get("debate_verdict") or {},
        "tools": [
            {
                "tool_name": item.get("tool_name"),
                "rule_id": item.get("rule_id"),
                "file_path": item.get("file_path"),
                "line_start": item.get("line_start"),
                "line_end": item.get("line_end"),
                "confidence": item.get("confidence"),
                "message": item.get("message"),
            }
            for item in source_observations
        ],
    }


def _tool_provenance(finding: dict[str, Any], source_observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    provenance: list[dict[str, Any]] = []
    own_tool = finding.get("tool_name")
    own_rule = finding.get("tool_rule_id") or finding.get("rule_id")
    if own_tool or own_rule:
        provenance.append(
            {
                "source": "finding",
                "tool_name": own_tool,
                "rule_id": own_rule,
                "normalized_rule_category": finding.get("normalized_rule_category"),
                "raw_artifact_id": finding.get("raw_artifact_id"),
            }
        )
    for observation in source_observations:
        provenance.append(
            {
                "source": "tool_observation",
                "tool_name": observation.get("tool_name"),
                "rule_id": observation.get("rule_id"),
                "raw_artifact_id": observation.get("raw_artifact_id"),
                "file_path": observation.get("file_path"),
                "line_start": observation.get("line_start"),
                "line_end": observation.get("line_end"),
            }
        )
    return provenance


def _mark_observations_adopted(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    agent_id: str,
    observations: list[dict[str, Any]],
) -> None:
    for observation in observations:
        conn.execute(
            """
            UPDATE tool_observations
            SET adopted_by_agent = ?, adoption_state = 'adopted_final'
            WHERE review_run_id = ?
              AND tool_name = ?
              AND COALESCE(rule_id, '') = COALESCE(?, '')
              AND file_path = ?
              AND COALESCE(line_start, -1) = COALESCE(?, -1)
              AND message = ?
            """,
            (
                agent_id,
                run_id,
                observation.get("tool_name"),
                observation.get("rule_id"),
                observation.get("file_path"),
                observation.get("line_start"),
                observation.get("message"),
            ),
        )


def judge_candidate_findings(
    findings: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    debate_results: list[dict[str, Any]] | None = None,
    max_findings: int = 20,
    selection_confidence: float = 0.75,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    weak_high_severity_hashes = {
        value
        for conflict in conflicts
        if conflict.get("type") == "high_severity_weak_evidence"
        for value in conflict.get("finding_hashes", [])
    }
    by_key: dict[tuple[str, str, int], dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []
    findings, debate_rejected = apply_debate_verdicts(findings, debate_results or [])
    rejected.extend(debate_rejected)

    for finding in findings:
        item = dict(finding)
        if item.get("dedupe_hash") in weak_high_severity_hashes and item.get("severity") in {"critical", "high"}:
            item["severity"] = "medium"
            item["judge_adjustment"] = "downgraded_high_severity_weak_evidence"
        key = _semantic_dedupe_key(item)
        current = by_key.get(key)
        if current is None:
            by_key[key] = _normalize_for_judging(item)
            continue
        if _priority_sort_key(item) > _priority_sort_key(current):
            rejected.append({**current, "rejected_reasons": ["deduped_lower_rank"]})
            by_key[key] = _merge_finding_metadata(_normalize_for_judging(item), current)
        else:
            rejected.append({**item, "rejected_reasons": ["deduped_lower_rank"]})
            by_key[key] = _merge_finding_metadata(current, item)

    candidates = list(by_key.values())
    if len(candidates) > max_findings:
        primary_candidates: list[dict[str, Any]] = []
        advisory_candidates: list[dict[str, Any]] = []
        for candidate in candidates:
            if _is_secondary_advisory_finding(candidate):
                advisory_candidates.append(candidate)
            else:
                primary_candidates.append(candidate)
        if len(primary_candidates) >= max_findings:
            rejected.extend({**candidate, "rejected_reasons": ["secondary_advisory_overflow"]} for candidate in advisory_candidates)
            candidates = primary_candidates
        else:
            candidates = [*primary_candidates, *advisory_candidates]

    ordered = sorted(candidates, key=_priority_sort_key, reverse=True)
    selected, selection_rejected = _select_with_category_coverage(ordered, max_findings)
    rejected.extend(selection_rejected)
    selected, auxiliary_rejected = _drop_auxiliary_overlaps(selected)
    rejected.extend(auxiliary_rejected)
    if len(selected) < max_findings:
        selected, fill_rejected = _fill_after_auxiliary_drop(selected, ordered, max_findings)
        rejected.extend(fill_rejected)

    for item in selected:
        item["selected"] = 1 if float(item.get("confidence") or 0) >= selection_confidence and item.get("severity") in SELECTABLE_SEVERITIES else 0

    return selected, rejected


def make_judge_findings_node(
    *,
    conn: sqlite3.Connection,
    recorder: Any,
    job: Any,
    project_id: str,
    run_id: str,
    new_id: Any,
    load_tool_observations: Any,
    max_findings: int = 20,
    selection_confidence: float = 0.75,
):
    def judge_findings_node(state: dict[str, Any]) -> dict[str, Any]:
        judge_span = recorder.span("judge_findings")
        tool_observations = state.get("tool_observations") or load_tool_observations(conn, run_id)
        tool_observations, diff_rejected_observations = filter_tool_observations_to_added_lines(tool_observations, state.get("files") or [])
        for observation in diff_rejected_observations:
            recorder.event(
                judge_span,
                "tool_observation_dropped",
                f"{observation.get('tool_name', 'static_tool')}:{observation.get('rule_id', 'unknown')} 未落在 MR 新增/修改行，已过滤",
                {
                    "tool_name": observation.get("tool_name"),
                    "rule_id": observation.get("rule_id"),
                    "file_path": observation.get("file_path"),
                    "line_start": observation.get("line_start"),
                    "reasons": observation.get("rejected_reasons") or [],
                },
            )
        promoted_findings = promote_tool_observations(tool_observations, state["verified_findings"])
        if promoted_findings:
            recorder.event(
                judge_span,
                "tool_observations_promoted",
                f"采纳 {len(promoted_findings)} 个高置信工具观察作为候选问题",
                {
                    "rules": sorted({rule for item in promoted_findings for rule in item.get("covered_rules", [])}),
                    "tool_observation_count": len(tool_observations),
                },
            )
        final_findings, judge_rejections = judge_candidate_findings(
            [*state["verified_findings"], *promoted_findings],
            state.get("conflicts") or [],
            state.get("debate_results") or [],
            max_findings=max_findings,
            selection_confidence=selection_confidence,
        )
        final_findings, diff_anchor_rejections = filter_to_diff_introduced_findings(final_findings, state.get("files") or [])
        judge_rejections.extend(diff_anchor_rejections)
        history = load_rule_precision_history(conn, project_id)
        final_findings, calibration_rejections = calibrate_findings_with_history(final_findings, history)
        judge_rejections.extend(calibration_rejections)
        final_findings = [ensure_actionable_suggested_code(item) for item in final_findings]
        for item in final_findings:
            flags = set(item.get("verification_flags") or [])
            item["selected"] = 0 if "invalid_suggested_code" in flags else 1 if float(item.get("confidence") or 0) >= selection_confidence and item.get("severity") in SELECTABLE_SEVERITIES else 0
        final_selected_findings: list[dict[str, Any]] = []
        for item in final_findings:
            if item.get("selected", 0):
                final_selected_findings.append(item)
                continue
            judge_rejections.append({**item, "rejected_reasons": ["not_selected_final_issue"]})
        final_findings = final_selected_findings
        for rejected in judge_rejections:
            reasons = rejected.get("rejected_reasons") or []
            recorder.event(
                judge_span,
                "finding_dropped",
                f"{rejected.get('title', 'candidate')} 被 Judge 过滤：{','.join(reasons)}",
                {"dedupe_hash": rejected.get("dedupe_hash"), "reasons": reasons},
            )
        for finding in final_findings:
            source_observations = match_tool_observations_for_finding(finding, tool_observations)
            own_observation = finding.get("source_tool_observation")
            if isinstance(own_observation, dict):
                own_trace = _observation_trace_item(own_observation)
                if not any(
                    item.get("tool_name") == own_trace.get("tool_name")
                    and item.get("rule_id") == own_trace.get("rule_id")
                    and item.get("file_path") == own_trace.get("file_path")
                    and item.get("line_start") == own_trace.get("line_start")
                    for item in source_observations
                ):
                    source_observations.insert(0, own_trace)
            finding = reconcile_rules_with_tool_observations(finding, source_observations)
            if _drop_without_tool_support(finding, source_observations):
                recorder.event(
                    judge_span,
                    "finding_dropped",
                    f"{finding.get('title', 'candidate')} 被 Judge 过滤：unsupported_low_precision_llm_finding",
                    {"dedupe_hash": finding.get("dedupe_hash"), "rules": finding.get("covered_rules") or []},
                )
                continue
            source_observations = [
                {**item, "adoption_state": "adopted_final", "adopted_by_agent": finding.get("agent_id")}
                for item in source_observations
            ]
            tool_provenance = _tool_provenance(finding, source_observations)
            quality_trace = build_quality_trace(finding, source_observations)
            conn.execute(
                """
                INSERT INTO review_findings (
                  id, review_run_id, severity, confidence, agent_id, head_sha, dedupe_hash,
                  file_path, line_start, line_end, title, problem_description, recommendation, suggested_code, evidence,
                  covered_rules_json, skipped_rules_json, tool_provenance_json, source_observations_json, quality_trace_json,
                  publish_state, lifecycle_state, selected
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'pending', ?)
                """,
                (
                    new_id("finding"),
                    run_id,
                    finding["severity"],
                    finding["confidence"],
                    finding["agent_id"],
                    job["head_sha"],
                    finding["dedupe_hash"],
                    finding["file_path"],
                    finding.get("line_start"),
                    finding.get("line_end"),
                    finding["title"],
                    finding["problem_description"],
                    finding["recommendation"],
                    str(finding.get("suggested_code") or "").strip(),
                    finding["evidence"],
                    json.dumps(finding.get("covered_rules", []), ensure_ascii=False),
                    json.dumps(finding.get("skipped_rules", []), ensure_ascii=False),
                    json.dumps(tool_provenance, ensure_ascii=False),
                    json.dumps(source_observations, ensure_ascii=False),
                    json.dumps(quality_trace, ensure_ascii=False),
                    int(finding.get("selected", 0)),
                ),
            )
            _mark_observations_adopted(
                conn,
                run_id=run_id,
                agent_id=str(finding.get("agent_id") or ""),
                observations=source_observations,
            )
        recorder.event(
            judge_span,
            "finding_merged",
            f"Judge 输出 {len(final_findings)} 个问题",
            {
                "tool_observation_count": len(tool_observations),
                "conflict_count": len(state.get("conflicts") or []),
                "debate_transcript_count": len(state.get("debate_transcripts") or []),
                "judge_rejected_count": len(judge_rejections),
            },
        )
        recorder.finish(judge_span)
        return {**state, "final_findings": final_findings}

    return judge_findings_node
