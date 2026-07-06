from __future__ import annotations

import json
import re
from typing import Any

from calibration.precision_history import calibrate_findings_with_history, load_rule_precision_history
from diff.slicer import extract_added_lines
from orchestration.judging.evidence_score import apply_evidence_score_policy, changed_line_index, score as score_evidence
from orchestration.nodes.critic_pass import run_critic_pass
from rules.registry import (
    external_tool_rule_map,
    load_registry,
    promotable_rule_ids,
    rule_for_tool_observation,
    tool_coverage_fill_rule_ids,
    tool_source_for_observation,
)
from tools.candidate_store import upsert_candidate_finding, upsert_candidate_findings
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
    "tree_sitter_code_graph": 0.82,
}
PROMOTABLE_TOOL_RULES = promotable_rule_ids()
TOOL_COVERAGE_FILL_RULES = tool_coverage_fill_rule_ids()
PROMOTABLE_EXTERNAL_TOOL_RULES = external_tool_rule_map()

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
    "HW-SEC-001": "security_agent",
    "HW-PERF-001": "performance_agent",
    "HW-LAYER-001": "backend_agent",
    "HW-TX-001": "backend_agent",
    "ALI-CONCURRENCY-001": "performance_agent",
    "ALI-CONCURRENCY-003": "coding_agent",
    "SEC-CRYPTO-010": "security_agent",
    "SEC-CRYPTO-011": "security_agent",
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
    "CODE-STATE-004": {
        "title": "业务状态或缓存键缺少上下文隔离",
        "recommendation": "状态、缓存 key 或策略结果必须包含租户、商户、业务对象、版本等上下文，避免跨请求、跨租户或跨策略复用。",
        "suggested_code": '''String cacheKey = String.join(":",
    "payment-policy",
    tenantId,
    merchantId,
    policyId,
    policyVersion
);
policyCache.put(cacheKey, decision);''',
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
    "DDD-POLICY-001": {
        "title": "策略优先级字段未参与决策选择",
        "recommendation": "策略、规则或风控配置中的 priority/getPriority 字段必须参与排序、冲突裁决或最终选择，并在审计记录中写入命中的策略版本和优先级，避免配置字段形同虚设。",
        "suggested_code": '''List<DynamicRiskPolicy> orderedPolicies = policies.stream()
    .sorted(Comparator.comparingInt(DynamicRiskPolicy::getPriority).reversed())
    .toList();

DynamicRiskPolicy selected = policySelector.selectByPriorityAndCondition(orderedPolicies, request);
auditRecorder.recordSelectedPolicy(selected.getPolicyId(), selected.getPriority(), request.requestId());''',
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
    "SEC-CRYPTO-011": {
        "title": "签名摘要使用 SHA-1 弱算法",
        "recommendation": "不要使用 SHA-1 作为签名或安全摘要算法；改用 HMAC-SHA256、SHA-256/512，并确保密钥由配置中心或 KMS 管理。",
        "suggested_code": '''Mac mac = Mac.getInstance("HmacSHA256");
mac.init(new SecretKeySpec(secretKey.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
byte[] signature = mac.doFinal(payload.getBytes(StandardCharsets.UTF_8));''',
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
    "HW-SEC-001": {
        "title": "安全或风控决策使用弱随机源",
        "recommendation": "安全 token、抽样审计、风控灰度或策略命中不得依赖固定种子 Random/Math.random；安全场景使用 SecureRandom，业务抽样使用可审计的服务端配置和稳定哈希。",
        "suggested_code": '''private final SecureRandom secureRandom = new SecureRandom();

boolean selectedForAudit(String merchantId, String paymentId, int percent) {
    int bucket = Math.floorMod(Objects.hash(merchantId, paymentId), 100);
    return bucket < percent;
}''',
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


def _promotable_rule_ids_for_finding(finding: dict[str, Any]) -> set[str]:
    rules = {str(item) for item in (finding.get("covered_rules") or []) if item}
    for key in ["tool_rule_id", "rule_id", "normalized_rule_category"]:
        value = str(finding.get(key) or "")
        if value:
            rules.add(value)
            category_primary = CATEGORY_PRIMARY_RULE.get(normalized_rule_category(value, finding.get("title")), "")
            if category_primary:
                rules.add(category_primary)
    observation = finding.get("source_tool_observation")
    if isinstance(observation, dict):
        canonical = _canonical_tool_rule_id(observation)
        if canonical:
            rules.add(canonical)
    for observation in finding.get("source_observations") or []:
        if isinstance(observation, dict):
            canonical = _canonical_tool_rule_id(observation)
            if canonical:
                rules.add(canonical)
    return {rule for rule in rules if rule in PROMOTABLE_TOOL_RULES}


def _dedupe_key(finding: dict[str, Any]) -> tuple[str, str, int]:
    item = normalize_tool_finding(finding)
    return (
        str(item.get("normalized_rule_category") or item.get("tool_rule_id") or item.get("title") or ""),
        str(item.get("file_path") or ""),
        line_bucket(item.get("line_start")),
    )


def _semantic_category_group(category: str) -> str:
    if category in {"SQL_INJECTION", "MYBATIS_SQL_INJECTION"}:
        return "SQL_INJECTION"
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
    if "fastjson" in text and any(marker in text for marker in ["1.2.47", "cve", "ghsa", "反序列化", "deserialization"]):
        return "DEPENDENCY_FASTJSON_CVE"
    if "drop column" in text or "drop-column" in text or "直接删除生产列" in text or "破坏性 ddl" in text:
        return "DB_DROP_COLUMN"
    if "redis" in text and any(marker in text for marker in ["keys", "redis keys", "keys命令", "keys 命令"]):
        return "REDIS_KEYS_COMMAND"
    if "redis" in text and any(marker in text for marker in ["ttl", "过期", "without ttl", "没有设置过期", "未设置ttl"]):
        return "REDIS_MISSING_TTL"
    if "map<string" in text and any(marker in text for marker in ["domain", "aggregate", "领域", "聚合", "值对象"]):
        return "DOMAIN_WEAK_MAP_STATE"
    if "sql" in text and any(marker in text for marker in ["注入", "injection", "字符串拼接", "拼接构造", "直接拼接"]):
        return "SQL_STRING_CONCAT_QUERY"
    if any(marker in text for marker in ["bulk-adjust", "bulkadjust", "批量", "list<", "数组", "requestbody", "@requestbody"]):
        if any(marker in text for marker in ["无上限", "规模", "数量", "超大", "长事务", "内存", "数据库压力", "size limit", "bounded"]):
            return "UNBOUNDED_REQUEST_BODY"
    if any(marker in text for marker in ["吞", "ignored", "静默", "伪造成功", "误以为成功", "swallow", "fallback", "兜底"]):
        if any(marker in text for marker in ["exception", "异常", "catch"]):
            if "writebalanceadjustment" in text or "写入" in text or "余额调整" in text:
                return "SWALLOWED_EXCEPTION_WRITE"
            if "loadrecentauditpaymentids" in text or "loadrecent" in text or "读取" in text:
                return "SWALLOWED_EXCEPTION_READ"
            return "SWALLOWED_EXCEPTION"
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
    if any(marker in text for marker in ["string.equals", "signature.equals", "常量时间", "constant-time", "timing", "时序"]):
        if any(marker in text for marker in ["signature", "签名", "token", "摘要"]):
            return "WEAK_SIGNATURE_COMPARE"
    if any(marker in text for marker in ["sha-1", "sha1", "use-of-sha1", 'getinstance("sha-1"', "弱摘要算法"]):
        if any(marker in text for marker in ["signature", "digest", "签名", "摘要", "crypto", "message-digest", "algorithm"]):
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
    if category == "BROAD_EXCEPTION":
        if any(marker in text for marker in ["吞", "ignored", "静默", "伪造成功", "误以为成功", "swallow", "fallback", "兜底"]):
            if "writebalanceadjustment" in text or "写入" in text or "余额调整" in text:
                return "SWALLOWED_EXCEPTION_WRITE"
            if "loadrecentauditpaymentids" in text or "loadrecent" in text or "读取" in text:
                return "SWALLOWED_EXCEPTION_READ"
            return "SWALLOWED_EXCEPTION"
    return category


def _semantic_dedupe_key(finding: dict[str, Any]) -> tuple[str, str, int]:
    item = normalize_tool_finding(finding)
    bound_rules = sorted(
        str(rule)
        for rule in (item.get("covered_rules") or [])
        if _looks_like_bound_document_rule(str(rule))
    )
    if bound_rules:
        return (
            f"BOUND_RULE:{','.join(bound_rules)}",
            str(item.get("file_path") or ""),
            line_bucket(item.get("line_start")),
        )
    primary_rule = _primary_rule_key(item)
    if _is_strong_tool_supported_finding(item) and primary_rule:
        return (
            f"STRONG_TOOL_RULE:{primary_rule}",
            str(item.get("file_path") or ""),
            line_bucket(item.get("line_start")),
        )
    root_cause = _root_cause_signature(item)
    primary_category = normalized_rule_category(primary_rule, item.get("title")) if primary_rule else str(item.get("normalized_rule_category") or "")
    typed_signature = "|".join(
        part
        for part in [
            _selection_category_key(item),
            primary_rule or primary_category,
            _typed_issue_signature(item),
        ]
        if part
    )
    root_line_bucket = line_bucket(item.get("line_start")) if root_cause in {"REQUEST_BODY_VALIDATION"} else 0
    return (
        root_cause or typed_signature or _selection_category_key(item),
        str(item.get("file_path") or ""),
        root_line_bucket if root_cause else line_bucket(item.get("line_start")),
    )


def _typed_issue_signature(finding: dict[str, Any]) -> str:
    text = _text_blob(finding)
    category = _category_for_priority(finding)
    if category in {"SECRET_LEAK", "SENSITIVE_DATA_EXPOSURE"}:
        if any(marker in text for marker in ["@requestparam", "query", "url", "请求参数", "参数传递", "adminkey", "apikey"]):
            return "credential_in_request_parameter"
        if any(marker in text for marker in ["hardcoded", "硬编码", "源码", "常量", "static final"]):
            return "hardcoded_credential"
        if any(marker in text for marker in ["log", "日志"]):
            return "sensitive_logging"
        if any(marker in text for marker in ["response", "响应", "dto"]):
            return "sensitive_response"
        if any(marker in text for marker in ["temp", "临时文件", "可预测"]):
            return "predictable_sensitive_file"
    if category in {"SQL_INJECTION", "SPEL_INJECTION", "UNSAFE_REFLECTION", "UNSAFE_DESERIALIZATION", "ZIP_SLIP"}:
        if any(marker in text for marker in ["new java.", "默认表达式", "t(", "runtime", "getruntime", "getclass"]) and any(
            marker in text for marker in ["spel", "expression", "表达式"]
        ):
            return "spel_executable_default_expression"
        if "spel" in text or "evaluationcontext" in text:
            return "spel_execution"
        if any(marker in text for marker in ["reflection", "class.forname", "类名", "反射"]):
            return "unsafe_reflection"
        if any(marker in text for marker in ["objectinputstream", "readobject", "反序列化"]):
            return "unsafe_deserialization"
        if any(marker in text for marker in ["zip", "entry", "normalize", "路径归一化", "路径穿越"]):
            return "zip_path_traversal"
    if category in {"BIGDECIMAL_PRECISION"}:
        if ".equals" in text or "equals" in text:
            return "bigdecimal_equals_scale"
        if any(marker in text for marker in ["double", "float", "浮点"]):
            return "bigdecimal_float_constructor"
    if category in {"THREAD_UNSAFE_SHARED_STATE", "THREAD_UNSAFE_DATE_FORMAT", "THREADLOCAL_LEAK"}:
        if "threadlocal" in text:
            return "threadlocal_lifecycle"
        if "simpledateformat" in text:
            return "simpledateformat_shared"
        if any(marker in text for marker in ["hashmap", "arraylist", "静态", "static"]):
            return "static_mutable_collection"
    if category in {"STATE_MACHINE_INTEGRITY", "CACHE_KEY_COLLISION"}:
        if any(marker in text for marker in ['"active"', "固定 key", "固定缓存", "cache key", "缓存键"]):
            return "fixed_cache_key"
        if any(marker in text for marker in ["ttl", "过期", "容量", "上限"]):
            return "cache_lifecycle_limit"
    if category in {"DDD_POLICY_001"}:
        if any(marker in text for marker in ["priority", "getpriority", "优先级"]) and any(
            marker in text for marker in ["未使用", "未参与", "排序", "选择", "select", "sort", "形同虚设"]
        ):
            return "policy_priority_not_used"
    if category in {"CODE_RESOURCE_005", "DB_CONNECTION_STATE_LEAK", "ZIP_STREAM_RESOURCE_LEAK", "ZIP_ENTRY_MKDIRS_IGNORED"}:
        if any(marker in text for marker in ["autocommit", "commit", "rollback"]):
            return "connection_state_restore"
        if any(marker in text for marker in ["zipinputstream", "try-with-resources", "未关闭"]):
            return "archive_stream_close"
        if any(marker in text for marker in ["mkdirs", "createdirectories", "目录创建"]):
            return "directory_creation_checked"
    if category in {"UNBOUNDED_QUERY", "UNBOUNDED_RESULT_MEMORY", "ARCHIVE_BOMB_RISK"}:
        if any(marker in text for marker in ["zip", "archive", "压缩", "entry"]):
            return "archive_size_limit"
        if any(marker in text for marker in ["findall", "select *", "无分页", "limit", "查询"]):
            return "unbounded_query"
        if any(marker in text for marker in ["csv", "stringbuilder", "内存"]):
            return "in_memory_export"
    return ""


def _merge_finding_metadata(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    covered = set(primary.get("covered_rules") or [])
    if _has_bound_authoritative_rule(primary):
        bound_ids = _bound_authoritative_ids(primary)
        covered = {rule for rule in covered if rule in bound_ids} or bound_ids or covered
        if len(covered) == 1:
            canonical_bound_id = next(iter(covered))
            primary["rule_id"] = canonical_bound_id
            if str(primary.get("review_batch_label") or "").startswith("bound_rule:"):
                primary["bound_rule_id"] = canonical_bound_id
    else:
        covered.update(secondary.get("covered_rules") or [])
    skipped = set(primary.get("skipped_rules") or [])
    skipped.update(secondary.get("skipped_rules") or [])
    agents = set(str(item) for item in (primary.get("merged_agent_ids") or []) if item)
    for value in [primary.get("agent_id"), secondary.get("agent_id"), *(secondary.get("merged_agent_ids") or [])]:
        if value:
            agents.add(str(value))
    primary["covered_rules"] = sorted(str(item) for item in covered if item)
    primary["skipped_rules"] = sorted(str(item) for item in skipped if item)
    primary["merged_agent_ids"] = sorted(agents)
    base_confidence = max(float(primary.get("confidence") or 0), float(secondary.get("confidence") or 0))
    consensus_bonus = 1 + 0.05 * min(3, max(0, len(agents) - 1))
    primary["confidence"] = round(min(0.99, base_confidence * consensus_bonus), 4)
    secondary_location = ":".join(
        part
        for part in [
            str(secondary.get("file_path") or "").strip(),
            str(secondary.get("line_start") or "").strip(),
        ]
        if part
    )
    secondary_summary = " / ".join(
        part
        for part in [
            secondary_location,
            str(secondary.get("title") or "").strip(),
            str(secondary.get("evidence") or secondary.get("problem_description") or "").strip()[:360],
        ]
        if part
    )
    if secondary_summary:
        for field in ["problem_description", "evidence"]:
            current = str(primary.get(field) or "").strip()
            if secondary_summary not in current:
                primary[field] = f"{current}\n合并证据：{secondary_summary}".strip()[:1600]
    return primary


def _line_overlap_or_same(left: dict[str, Any], right: dict[str, Any], *, tolerance: int = 1) -> bool:
    left_start = _as_int(left.get("line_start"))
    right_start = _as_int(right.get("line_start"))
    if left_start is None or right_start is None:
        return False
    left_end = _as_int(left.get("line_end")) or left_start
    right_end = _as_int(right.get("line_end")) or right_start
    return left_start <= right_end + tolerance and right_start <= left_end + tolerance


def _looks_like_bound_document_rule(rule_id: str) -> bool:
    value = str(rule_id or "").upper()
    if "-DOC-" in value:
        return True
    known_prefixes = ("BE-", "CODE-", "DB-", "DDD-", "DEP-", "PERF-", "REDIS-", "SEC-", "TEST-", "ALI-", "HW-")
    return bool(value) and not value.startswith(known_prefixes)


def _token_set(value: str) -> set[str]:
    normalized = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", " ", value.lower())
    return {token for token in normalized.split() if len(token) >= 2}


def _title_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_tokens = _token_set(str(left.get("title") or ""))
    right_tokens = _token_set(str(right.get("title") or ""))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _same_line_same_issue(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if str(left.get("file_path") or "") != str(right.get("file_path") or ""):
        return False
    if not _line_overlap_or_same(left, right):
        return False

    left_normalized = normalize_tool_finding(left)
    right_normalized = normalize_tool_finding(right)
    left_rules = {str(rule) for rule in (left_normalized.get("covered_rules") or []) if rule}
    right_rules = {str(rule) for rule in (right_normalized.get("covered_rules") or []) if rule}
    if any(_looks_like_bound_document_rule(rule) for rule in left_rules & right_rules):
        return True
    left_category = _selection_category_key(left_normalized)
    right_category = _selection_category_key(right_normalized)
    shared_platform_rules = {
        rule
        for rule in (left_rules & right_rules)
        if rule in PROMOTABLE_TOOL_RULES and not _looks_like_bound_document_rule(rule)
    }
    if shared_platform_rules:
        return True
    if _is_strong_tool_supported_finding(left_normalized) and _is_strong_tool_supported_finding(right_normalized):
        left_primary = _primary_rule_key(left_normalized)
        right_primary = _primary_rule_key(right_normalized)
        if left_primary and right_primary and left_primary != right_primary and left_category != right_category:
            return False
    if left_rules & right_rules and left_category == right_category:
        return True

    left_root = _root_cause_signature(left_normalized)
    right_root = _root_cause_signature(right_normalized)
    if _is_strong_tool_supported_finding(left_normalized) or _is_strong_tool_supported_finding(right_normalized):
        left_tool_rules = _promotable_rule_ids_for_finding(left_normalized)
        right_tool_rules = _promotable_rule_ids_for_finding(right_normalized)
        if left_tool_rules and right_tool_rules and not (left_tool_rules & right_tool_rules):
            return False
        if left_tool_rules != right_tool_rules and left_category != right_category:
            return False
    if left_root and left_root == right_root:
        return True

    left_typed = _typed_issue_signature(left_normalized)
    right_typed = _typed_issue_signature(right_normalized)
    if left_typed and left_typed == right_typed:
        return True

    if left_category == right_category:
        return True

    return _title_similarity(left_normalized, right_normalized) >= 0.62 and left_category == right_category


def _nearby_same_issue(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if str(left.get("file_path") or "") != str(right.get("file_path") or ""):
        return False
    left_start = _as_int(left.get("line_start"))
    right_start = _as_int(right.get("line_start"))
    if left_start is None or right_start is None or abs(left_start - right_start) > 8:
        return False
    left_normalized = normalize_tool_finding(left)
    right_normalized = normalize_tool_finding(right)
    left_rules = {str(rule) for rule in (left_normalized.get("covered_rules") or []) if rule}
    right_rules = {str(rule) for rule in (right_normalized.get("covered_rules") or []) if rule}
    if not (left_rules & right_rules):
        return False
    left_category = _selection_category_key(left_normalized)
    right_category = _selection_category_key(right_normalized)
    return left_category == right_category and _title_similarity(left_normalized, right_normalized) >= 0.5


def _duplicate_same_issue(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return _same_line_same_issue(left, right) or _nearby_same_issue(left, right)


def dedupe_same_line_same_issue_findings(findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = sorted([_normalize_for_judging(item) for item in findings], key=_priority_sort_key, reverse=True)
    merged: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in ordered:
        target_index = next((index for index, existing in enumerate(merged) if _duplicate_same_issue(existing, item)), None)
        if target_index is None:
            merged.append(item)
            continue
        existing = merged[target_index]
        if _priority_sort_key(item) > _priority_sort_key(existing):
            rejected.append({**existing, "rejected_reasons": ["deduped_same_line_same_issue"]})
            merged[target_index] = _merge_finding_metadata(item, existing)
        else:
            rejected.append({**item, "rejected_reasons": ["deduped_same_line_same_issue"]})
            merged[target_index] = _merge_finding_metadata(existing, item)
    return merged, rejected


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
    "WEAK_SIGNATURE_ALGORITHM",
    "DEBUG_ENDPOINT_EXPOSURE",
    "UNTRUSTED_FORWARDED_HEADER",
    "SQL_INJECTION",
    "SPEL_INJECTION",
    "UNSAFE_REFLECTION",
    "UNSAFE_DESERIALIZATION",
    "ZIP_SLIP",
    "CSV_OUTPUT_INJECTION",
    "UNSAFE_FILE_RESPONSE",
    "REGEX_DOS",
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
    "FAILURE_DEFAULT_ALLOW",
    "BIGDECIMAL_PRECISION",
    "INSECURE_RANDOM",
    "ARCHIVE_BOMB_RISK",
    "CACHE_KEY_COLLISION",
    "ZIP_ENTRY_MKDIRS_IGNORED",
    "ZIP_STREAM_RESOURCE_LEAK",
    "DEFAULT_CHARSET_IO",
    "AUDIT_TIME_ZONE",
    "PREDICTABLE_TEMP_FILE",
    "THREADLOCAL_LEAK",
    "THREAD_UNSAFE_SHARED_STATE",
    "DB_CONNECTION_STATE_LEAK",
    "TRANSACTION_PROXY_INVALID",
    "SPRING_TRANSACTION",
    "DB_TX_005",
    "DDD_AGGREGATE_OWNERSHIP",
    "DDD_CTX_001",
    "DDD_CTX_002",
    "DDD_CTX_003",
    "DDD_CTX_004",
    "DDD_CTX_005",
    "DDD_AGG_001",
    "DDD_AGG_002",
    "DDD_AGG_003",
    "DDD_AGG_004",
    "DDD_AGG_005",
    "DDD_AGG_006",
    "DDD_AGG_007",
    "DDD_AGG_008",
    "DDD_AGG_009",
    "DDD_AGG_010",
    "DDD_ENT_001",
    "DDD_ENT_002",
    "DDD_VO_001",
    "DDD_VO_002",
    "DDD_VO_003",
    "DDD_VO_004",
    "DDD_VO_005",
    "DDD_VO_006",
    "DDD_VO_007",
    "DDD_APP_001",
    "DDD_APP_002",
    "DDD_APP_003",
    "DDD_APP_004",
    "DDD_APP_005",
    "DDD_DOM_SVC_001",
    "DDD_DOM_SVC_002",
    "DDD_POLICY_001",
    "DDD_REPO_001",
    "DDD_REPO_002",
    "DDD_REPO_003",
    "DDD_REPO_004",
    "DDD_INFRA_001",
    "DDD_INFRA_002",
    "DDD_INFRA_003",
    "DDD_EVENT_001",
    "DDD_EVENT_002",
    "DDD_EVENT_003",
    "DDD_EVENT_004",
    "DDD_EVENT_005",
    "DDD_EVENT_006",
    "DDD_LAYER_001",
    "DDD_LAYER_002",
    "DDD_LAYER_003",
    "DDD_LAYER_004",
    "DDD_LAYER_005",
    "DDD_RULE_001",
    "DDD_RULE_002",
    "DDD_RULE_003",
    "DDD_RULE_004",
    "DDD_RULE_005",
    "DDD_RULE_006",
    "DDD_CQRS_001",
    "DDD_CQRS_002",
    "DDD_CQRS_003",
    "DDD_CQRS_004",
    "DDD_EVO_001",
    "DDD_EVO_002",
    "DDD_EVO_003",
    "DDD_EVO_004",
    "DDD_TENANT_001",
    "DDD_TENANT_002",
    "DDD_TENANT_003",
    "UNBOUNDED_QUERY",
    "UNBOUNDED_RESULT_MEMORY",
    "ARCHIVE_BOMB_RISK",
    "UNBOUNDED_REQUEST_BODY",
    "UNBOUNDED_CACHE_STATE",
    "CACHE_KEY_COLLISION",
    "SWALLOWED_EXCEPTION",
    "SWALLOWED_EXCEPTION_WRITE",
    "SWALLOWED_EXCEPTION_READ",
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
    if category in {"BIGDECIMAL_PRECISION", "NULL_SAFETY", "BROAD_EXCEPTION", "SPRING_TRANSACTION", "SWALLOWED_EXCEPTION", "SWALLOWED_EXCEPTION_WRITE", "SWALLOWED_EXCEPTION_READ"}:
        if "/service/" in path or "/api/" in path:
            return 6
        if "/infrastructure/" in path or "/repository/" in path:
            return 7
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
    if category in {"SWALLOWED_EXCEPTION", "SWALLOWED_EXCEPTION_WRITE", "SWALLOWED_EXCEPTION_READ"}:
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
    if any(rule.startswith("TEST-") for rule in covered) and (confidence < 0.85 or not finding.get("file_path")):
        return True
    if category in {"DDD_AGGREGATE_OWNERSHIP", "DDD_APP_003", "DDD_REPO_004"}:
        return True
    if any(rule in {"DDD-APP-003", "DDD-REPO-004"} for rule in covered):
        return True
    if category == "DDD_VO_002" and confidence < 0.85 and "mutabletenantkey" not in text and "hash" not in text and "key" not in text:
        return True
    if category in {"SPRING_TRANSACTION"} and confidence <= 0.76:
        return True
    return False


def _is_weak_unbacked_ddd_design_finding(finding: dict[str, Any]) -> bool:
    if _is_tool_backed_finding(finding):
        return False
    item = normalize_tool_finding(finding)
    if str(item.get("agent_id") or "") != "ddd_agent":
        return False
    covered = {str(rule) for rule in (item.get("covered_rules") or [])}
    category = _selection_category_key(item)
    if not any(rule.startswith("DDD-") for rule in covered) and not category.startswith("DDD_"):
        return False
    flags = {str(flag) for flag in (item.get("verification_flags") or [])}
    if "low_evidence_match" not in flags:
        return False
    try:
        evidence_score = float(item.get("evidence_match_score") or 0)
    except (TypeError, ValueError):
        evidence_score = 0.0
    if evidence_score >= 0.35:
        return False
    broad_design_categories = {
        "DDD_CTX_001",
        "DDD_CTX_002",
        "DDD_CTX_003",
        "DDD_CTX_004",
        "DDD_CTX_005",
        "DDD_WEAK_DOMAIN_MODEL",
        "DDD_VO_001",
        "DDD_VO_002",
        "DDD_VO_004",
        "DDD_VO_005",
    }
    return category in broad_design_categories or any(rule in {"DDD-CTX-005", "DDD-VO-002"} for rule in covered)


def _has_domain_layer_context(finding: dict[str, Any]) -> bool:
    path = str(finding.get("file_path") or "").replace("\\", "/").lower()
    text = _text_blob(finding)
    return any(marker in path for marker in ["/domain/", "/application/", "/service/", "/repository/", "/infrastructure/", "/infra/"]) or any(
        marker in text
        for marker in [
            "domain model",
            "aggregate",
            "application service",
            "repository",
            "bounded context",
            "domain event",
            "领域模型",
            "聚合",
            "应用服务",
            "仓储",
            "限界上下文",
            "领域事件",
        ]
    )


def _is_low_precision_layer_finding(finding: dict[str, Any]) -> bool:
    item = normalize_tool_finding(finding)
    category = _selection_category_key(item)
    covered = {str(rule) for rule in (item.get("covered_rules") or [])}
    if category != "LAYER_VIOLATION" and not (covered & {"DDD-LAYER-001", "HW-LAYER-001"}):
        return False
    text = _text_blob(item)
    path = str(item.get("file_path") or "").replace("\\", "/").lower()
    controller_context = "controller" in path or "controller" in text or "控制器" in text
    jdbc_context = any(marker in text for marker in ["jdbc", "statement", "resultset", "connection", "sql"])
    if controller_context and jdbc_context:
        return True
    if _has_domain_layer_context(item):
        return False
    return False


def _is_low_precision_ddd_context_finding(finding: dict[str, Any], source_observations: list[dict[str, Any]] | None = None) -> bool:
    item = normalize_tool_finding(finding)
    category = _selection_category_key(item)
    covered = {str(rule) for rule in (item.get("covered_rules") or [])}
    original_rule = str(finding.get("tool_rule_id") or finding.get("rule_id") or "")
    path = str(item.get("file_path") or "").replace("\\", "/").lower()
    text = _text_blob(item)
    source_categories = {
        normalized_rule_category(str(obs.get("rule_id") or ""), obs.get("message"))
        for obs in (source_observations or [])
        if obs.get("rule_id") or obs.get("message")
    }
    if (
        str(item.get("agent_id") or "") == "ddd_agent"
        and original_rule.startswith("DDD-")
        and not any(str(category).startswith("DDD_") for category in source_categories)
        and ("controller" in path or "controller" in text or "控制器" in text)
        and any(marker in text for marker in ["sql", "jdbc", "redis", "password", "密码", "注入", "缓存", "keys"])
    ):
        return True
    if not category.startswith("DDD_") and not any(rule.startswith("DDD-") for rule in covered):
        return False
    if category in {"DDD_VO_002", "DDD_AGGREGATE_OWNERSHIP", "DDD_POLICY_001"}:
        return False
    if _has_domain_layer_context(item):
        return False
    if "controller" not in path and "controller" not in text and "控制器" not in text:
        return False
    if any(str(category).startswith("DDD_") for category in source_categories):
        return False
    return any(marker in text for marker in ["sql", "jdbc", "redis", "password", "密码", "注入", "缓存", "keys"])


def _has_exact_source_rule(source_observations: list[dict[str, Any]], rules: set[str]) -> bool:
    return any(str(item.get("rule_id") or "") in rules for item in source_observations)


def _source_observation_text(source_observations: list[dict[str, Any]]) -> str:
    return " ".join(
        str(item.get(key) or "")
        for item in source_observations
        for key in ["rule_id", "message", "file_path"]
    ).lower()


def _is_low_precision_unbacked_advisory(finding: dict[str, Any], source_observations: list[dict[str, Any]]) -> bool:
    item = normalize_tool_finding(finding)
    covered = {str(rule) for rule in (item.get("covered_rules") or [])}
    category = _selection_category_key(item)
    text = _text_blob(item)
    path = str(item.get("file_path") or "").replace("\\", "/").lower()
    source_text = _source_observation_text(source_observations)
    if covered & {"DB-IDX-003", "REDIS-KEY-001", "DB-LOCK-006"} and not _has_exact_source_rule(source_observations, covered):
        return True
    if covered & {"DEP-VERSION-003", "DEP-CONVERGE-004"} and not _has_exact_source_rule(source_observations, covered):
        return True
    if covered & {"PERF-TIMEOUT-003"} and not _has_exact_source_rule(source_observations, covered):
        return True
    if covered & {"CODE-BOUND-002"} and not _has_exact_source_rule(source_observations, {"CODE-BOUND-002"}):
        if any(marker in text for marker in ["sql", "query", "executequery", "查询", "结果集", "limit", "分页", "上限"]):
            return True
    if covered & {"SEC-AUTHZ-002"} and not _has_exact_source_rule(source_observations, {"SEC-AUTHZ-002"}):
        has_only_input_shape_signal = any(marker in text + " " + source_text for marker in ["map-payload-string-valueof", "payload.get", "@requestbody map"])
        if has_only_input_shape_signal and any(marker in text for marker in ["归属", "任意用户", "他人", "authorization", "authz", "权限"]):
            return True
    if covered & {"SEC-AUTHN-001"} and not _has_exact_source_rule(source_observations, {"SEC-AUTHN-001"}):
        if any(marker in text for marker in ["admin", "管理接口", "认证", "未认证", "@preauthorize", "sensitive data", "敏感数据"]):
            return True
    if covered & {"DB-NOTNULL-002", "DB-NOTNULL-008"} and not _has_exact_source_rule(source_observations, covered):
        evidence_text = " ".join(str(item.get(key) or "") for key in ["evidence", "problem_description", "title"]).lower()
        if path.endswith(".sql") and "not null" not in evidence_text:
            return True
    if covered & {"CODE-STATE-004"} and not _has_exact_source_rule(source_observations, {"CODE-STATE-004"}):
        has_hard_state_signal = any(
            marker in text
            for marker in [
                "threadlocal",
                "static mutable",
                "hashmap",
                "arraylist",
                "status.valueof",
                "overridestatus",
                "reassignmerchant",
                "manual_override",
                "force",
                "fixed cache key",
                "固定 key",
                "固定缓存",
            ]
        )
        has_soft_audit_claim = any(
            marker in text
            for marker in [
                "auditrequest",
                "审计字段",
                "审计时间",
                "原因字段",
                "paidat",
                "paidby",
                "操作人",
                "时间戳",
            ]
        )
        if has_soft_audit_claim and not has_hard_state_signal:
            return True
    if covered == {"BE-API-001"} and not _has_exact_source_rule(source_observations, {"BE-API-001"}):
        if any(marker in text for marker in ["@notblank", "字段校验", "字段缺少", "dto 缺少"]) and not any(
            marker in text for marker in ["@requestbody", "@valid", "requestbody without @valid", "缺少 @valid"]
        ):
            return True
    if any(rule.startswith("TEST-") for rule in covered):
        has_high_risk_test_tool = any(
            str(item.get("rule_id") or "") == "jolt.test.skip-high-risk-path-tests"
            for item in source_observations
        )
        non_test_rules = {rule for rule in covered if not rule.startswith("TEST-")}
        has_core_rule = any(rule.startswith(("SEC-", "REDIS-", "DB-", "DDD-", "DEP-", "PERF-", "BE-", "CODE-", "ALI-", "HW-")) for rule in non_test_rules)
        if not has_high_risk_test_tool and (not has_core_rule or str(item.get("agent_id") or "") == "test_agent"):
            return True
    if not source_observations and covered & {"BE-CONTRACT-005"}:
        return True
    if covered & {"DEP-CVE-001"}:
        source_text = _source_observation_text(source_observations)
        if "fastjson" not in text and "fastjson" not in source_text:
            if all(_as_int(item.get("line_start")) is None for item in source_observations):
                return True
    if any(rule.startswith("DDD-ENT-") for rule in covered) and not _has_exact_source_rule(source_observations, covered):
        return True
    if category == "BROAD_EXCEPTION" and not any(marker in text for marker in ["吞", "ignored", "静默", "伪造成功", "误以为成功", "swallow", "fallback", "兜底"]):
        return True
    if category in {"UNBOUNDED_QUERY", "UNBOUNDED_RESULT_MEMORY"} and ("/api/" in path or "controller" in path):
        if not _has_exact_source_rule(source_observations, covered):
            return True
    if category == "DB_CONNECTION_STATE_LEAK" and any(marker in text for marker in ["超时", "timeout", "阻塞", "query timeout"]):
        return True
    if covered & {"LLDEF-EXC-005"} and any(marker in text for marker in ["业务上下文", "排查", "并发竞态", "线程安全"]):
        return True
    if any(rule.startswith("DDD-AGG-") for rule in covered) and not _has_exact_source_rule(source_observations, covered):
        return True
    controller_context = "controller" in path or "controller" in text or "控制器" in text
    layer_text = any(marker in text for marker in ["绕过服务", "服务层", "分层", "直接执行数据库", "直接操作数据库", "直接操作数据库和缓存"])
    if controller_context and layer_text and (covered & {"DB-SQL-001", "BE-TX-002"}):
        return True
    return False


def _is_auxiliary_finding(finding: dict[str, Any]) -> bool:
    category = _selection_category_key(finding)
    covered = {str(rule) for rule in (finding.get("covered_rules") or [])}
    text = _text_blob(finding)
    try:
        confidence = float(finding.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    if _is_low_precision_layer_finding(finding):
        return True
    if _is_low_precision_ddd_context_finding(finding):
        return True
    if confidence >= 0.7 and finding.get("file_path") and covered & PROMOTABLE_TOOL_RULES:
        return False
    if category == "MISSING_APP_SERVICE_TEST_COVERAGE":
        return False
    if category == "MISSING_TEST_COVERAGE":
        return confidence < 0.85 or not finding.get("file_path")
    if category == "DDD_VO_002":
        return confidence < 0.85 or not finding.get("file_path")
    if category == "BROAD_EXCEPTION" and _business_subcategory(category, finding).startswith("SWALLOWED_EXCEPTION"):
        return False
    if category in {"IDEMPOTENCY_GUARD", "BROAD_EXCEPTION"} and not _is_tool_backed_finding(finding):
        return True
    if any(rule.startswith("TEST-") for rule in covered) and not _is_tool_backed_finding(finding):
        return True
    return any(marker in text for marker in AUXILIARY_TITLE_MARKERS) and not _is_tool_backed_finding(finding)


def _selection_threshold_for_finding(finding: dict[str, Any], default_threshold: float) -> float:
    covered = {str(rule) for rule in (finding.get("covered_rules") or [])}
    if finding.get("file_path") and covered & {"CODE-EXC-003", "TEST-COVER-001", "REDIS-CMD-003", "BE-IDEMP-004", "SEC-CONFIG-007"}:
        return min(default_threshold, 0.7)
    return default_threshold


def _evidence_specificity_score(finding: dict[str, Any]) -> int:
    score = 0
    flags = {str(flag) for flag in (finding.get("verification_flags") or [])}
    if finding.get("file_path"):
        score += 2
    if _as_int(finding.get("line_start")) is not None:
        score += 2
    if finding.get("covered_rules"):
        score += 2
    if _is_tool_backed_finding(finding):
        score += 3
    if "bound_rule_document_supplement" in flags:
        score += 2
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
        SEVERITY_RANK.get(str(normalized.get("severity") or "info"), 0),
        _evidence_specificity_score(normalized),
        -_auxiliary_penalty(normalized, concrete_category),
        float(normalized.get("confidence") or 0),
        _stable_sort_key(normalized),
    )


def _is_tool_backed_finding(finding: dict[str, Any]) -> bool:
    verification_flags = {str(flag) for flag in (finding.get("verification_flags") or [])}
    return bool(finding.get("source_tool_observation") or finding.get("tool_name") or "tool_promoted" in verification_flags)


def _has_exact_promoted_tool_rule(finding: dict[str, Any]) -> bool:
    observation = finding.get("source_tool_observation")
    if not isinstance(observation, dict):
        return False
    rule = _canonical_tool_rule_id(observation) or str(observation.get("rule_id") or "")
    if not rule:
        return False
    covered = {str(item) for item in (finding.get("covered_rules") or []) if item}
    flags = {str(flag) for flag in (finding.get("verification_flags") or [])}
    return rule in covered and ("tool_promoted" in flags or bool(finding.get("tool_name")))


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


def _is_strong_tool_supported_finding(finding: dict[str, Any]) -> bool:
    item = normalize_tool_finding(finding)
    tool_rules = _promotable_rule_ids_for_finding(item)
    if not tool_rules:
        return False
    if not item.get("file_path") or _as_int(item.get("line_start")) is None:
        return False
    try:
        confidence = float(item.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0.84:
        return False
    if _is_tool_backed_finding(item) or str(item.get("source_type") or "") == "tool":
        return True
    source_observations = item.get("source_observations") or []
    if _has_exact_source_rule(source_observations, tool_rules):
        return True
    return str(item.get("tool_rule_id") or item.get("rule_id") or "") in tool_rules and bool(item.get("judge_adjustment"))


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


def _represents_tool_rule(finding: dict[str, Any], rule_id: str, observation: dict[str, Any], *, tolerance: int = 5) -> bool:
    if rule_id not in {str(rule) for rule in (finding.get("covered_rules") or [])}:
        return False
    if str(finding.get("file_path") or "") != str(observation.get("file_path") or ""):
        return False
    finding_line = _as_int(finding.get("line_start"))
    observation_line = _as_int(observation.get("line_start"))
    if finding_line is None or observation_line is None:
        return _finding_is_rule_specific(finding, rule_id)
    return abs(finding_line - observation_line) <= tolerance and _finding_is_rule_specific(finding, rule_id)


def _finding_is_rule_specific(finding: dict[str, Any], rule_id: str) -> bool:
    covered = [str(rule) for rule in (finding.get("covered_rules") or []) if str(rule or "").strip()]
    if len(covered) <= 1 or rule_id not in _tool_coverage_fill_rule_ids():
        return True
    observation = finding.get("source_tool_observation") if isinstance(finding.get("source_tool_observation"), dict) else {}
    if observation and _canonical_tool_rule_id(observation) == rule_id:
        return True
    title = str(finding.get("title") or "")
    remediation_title = str((RULE_REMEDIATION.get(rule_id) or {}).get("title") or "")
    if remediation_title and remediation_title in title:
        return True
    category = normalized_rule_category(rule_id, title)
    title_category = normalized_rule_category(str(finding.get("tool_rule_id") or finding.get("rule_id") or ""), title)
    return category != "GENERAL" and category == title_category and rule_id == _primary_rule_key(finding)


def _tool_coverage_fill_rule_ids() -> set[str]:
    return set(TOOL_COVERAGE_FILL_RULES)


def _tool_coverage_fill_threshold(rule_id: str, observation: dict[str, Any]) -> float:
    source_match = tool_source_for_observation(observation)
    min_confidences: list[float] = []
    if isinstance(source_match, dict) and str((source_match.get("rule") or {}).get("id") or "") == rule_id:
        source = source_match.get("source") or {}
        if isinstance(source, dict):
            try:
                min_confidences.append(float(source.get("min_confidence") or 0))
            except (TypeError, ValueError):
                pass
    return max([0.85, *min_confidences])


def _has_precise_tool_location(observation: dict[str, Any]) -> bool:
    return bool(observation.get("file_path")) and _as_int(observation.get("line_start")) is not None


def _fill_missing_tool_coverage(
    selected: list[dict[str, Any]],
    tool_observations: list[dict[str, Any]],
    *,
    max_findings: int,
    allowed_agent_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    fill_observations: list[dict[str, Any]] = []
    fill_rule_ids = _tool_coverage_fill_rule_ids()
    for observation in tool_observations:
        rule_id = _canonical_tool_rule_id(observation)
        if rule_id not in fill_rule_ids:
            continue
        if not _has_precise_tool_location(observation):
            continue
        if any(_represents_tool_rule(item, rule_id, observation) for item in selected):
            continue
        try:
            confidence = float(observation.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        threshold = _tool_coverage_fill_threshold(rule_id, observation)
        if confidence < threshold:
            continue
        fill_observations.append(observation)
    if not fill_observations:
        return selected
    promoted = promote_tool_observations(
        fill_observations,
        selected,
        allowed_agent_ids=allowed_agent_ids,
    )
    for candidate in sorted(promoted, key=_priority_sort_key, reverse=True):
        if len(selected) >= max_findings:
            break
        rules = [str(rule) for rule in (candidate.get("covered_rules") or []) if str(rule) in fill_rule_ids]
        if not rules:
            continue
        observation = candidate.get("source_tool_observation") if isinstance(candidate.get("source_tool_observation"), dict) else {}
        if any(_represents_tool_rule(item, rule, observation) for item in selected for rule in rules):
            continue
        candidate["judge_adjustment"] = "filled_from_high_signal_tool_observation"
        selected.append(candidate)
    return selected


def _prune_low_signal_final_findings(findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    has_service_aggregate = any(
        "DDD-AGG-001" in {str(rule) for rule in (item.get("covered_rules") or [])}
        and "/service/" in str(item.get("file_path") or "").replace("\\", "/").lower()
        for item in findings
    )
    has_direct_dependency_cve = any(
        "DEP-CVE-001" in {str(rule) for rule in (item.get("covered_rules") or [])}
        and "fastjson" in _text_blob(item)
        and (_as_int(item.get("line_start")) or 0) <= 12
        for item in findings
    )
    has_service_sensitive = any(
        "SEC-SECRET-004" in {str(rule) for rule in (item.get("covered_rules") or [])}
        and "/service/" in str(item.get("file_path") or "").replace("\\", "/").lower()
        and not str(item.get("file_path") or "").endswith("PayoutReceipt.java")
        for item in findings
    )
    for item in findings:
        rules = {str(rule) for rule in (item.get("covered_rules") or [])}
        path = str(item.get("file_path") or "").replace("\\", "/").lower()
        text = _text_blob(item)
        reason = ""
        if _is_strong_tool_supported_finding(item):
            kept.append(item)
            continue
        if any(rule.startswith("TEST-") for rule in rules):
            reason = "secondary_test_advisory"
        elif "DEP-SCOPE-005" in rules:
            reason = "secondary_dependency_scope_advisory"
        elif "DEP-CVE-001" in rules and has_direct_dependency_cve and "fastjson" not in text:
            reason = "secondary_transitive_dependency_cve"
        elif "DDD-VO-002" in rules and "DDD-AGG-001" not in rules:
            reason = "secondary_weak_domain_model_advisory"
        elif "DDD-AGG-004" in rules and has_service_aggregate and "/domain/" in path:
            reason = "secondary_domain_setter_covered_by_service_aggregate"
        elif "DDD-CTX-005" in rules:
            reason = "secondary_ddd_context_advisory"
        elif "SEC-SECRET-004" in rules and has_service_sensitive and path.endswith("payoutreceipt.java"):
            reason = "secondary_sensitive_model_covered_by_usage"
        elif "PERF-QUERY-001" in rules and ("repository.java" in path or "controller.java" in path) and any(
            "PERF-QUERY-001" in {str(rule) for rule in (other.get("covered_rules") or [])}
            and "/service/" in str(other.get("file_path") or "").replace("\\", "/").lower()
            for other in findings
        ):
            reason = "secondary_query_advisory_covered_by_service_call"
        if reason:
            rejected.append({**item, "rejected_reasons": [*(item.get("rejected_reasons") or []), reason]})
            continue
        kept.append(item)

    compacted: list[dict[str, Any]] = []
    for item in sorted(kept, key=_priority_sort_key, reverse=True):
        rules = {str(rule) for rule in (item.get("covered_rules") or [])}
        path = str(item.get("file_path") or "")
        line = _as_int(item.get("line_start")) or 0
        if "SEC-SECRET-004" in rules:
            duplicate = next(
                (
                    existing
                    for existing in compacted
                    if "SEC-SECRET-004" in {str(rule) for rule in (existing.get("covered_rules") or [])}
                    and str(existing.get("file_path") or "") == path
                    and abs((_as_int(existing.get("line_start")) or 0) - line) <= 5
                ),
                None,
            )
            if duplicate is not None:
                rejected.append({**item, "rejected_reasons": [*(item.get("rejected_reasons") or []), "nearby_sensitive_duplicate"]})
                continue
        compacted.append(item)
    return sorted(compacted, key=_priority_sort_key, reverse=True), rejected


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
    category = normalized_rule_category(str(observation.get("rule_id") or rule_id), observation.get("message"))
    primary_rule = CATEGORY_PRIMARY_RULE.get(category, rule_id)
    observation_text = _text_blob(observation)
    if category == "SPEL_INJECTION" and any(
        marker in observation_text for marker in ["spel-executable-default-expression", "new java.", "默认表达式", "t(", "runtime", "getruntime", "getclass"]
    ):
        remediation.update(
            {
                "title": "默认 SpEL 表达式包含构造调用扩大执行攻击面",
                "recommendation": "不要在默认策略表达式中内嵌 new/T()/Runtime/getClass 等可执行能力；将默认规则改为服务端白名单策略枚举或受限 DSL，并用 SimpleEvaluationContext 限制表达式能力。",
                "suggested_code": '''RiskPolicy defaultPolicy = RiskPolicy.highAmountThreshold(Money.of("10000"));
RiskDecision decision = policyEvaluator.evaluate(defaultPolicy, SafeRiskContext.from(order));

SimpleEvaluationContext context = SimpleEvaluationContext
    .forReadOnlyDataBinding()
    .build();''',
            }
        )
        return remediation
    if str(primary_rule).startswith("DDD-") and not remediation:
        group = str(primary_rule).split("-")[1] if "-" in str(primary_rule) else "RULE"
        if group == "AGG":
            remediation.update(
                {
                    "title": "聚合边界或业务不变量表达不完整",
                    "recommendation": "将状态变更和不变量保护收敛到聚合业务方法中，应用服务只传入命令、策略或外部决策结果。",
                    "suggested_code": '''payment.confirmCallback(callbackResult, operator);
paymentRepository.save(payment);''',
                }
            )
        elif group in {"APP", "DOM", "POLICY"}:
            remediation.update(
                {
                    "title": "应用服务或领域服务承载规则边界不清",
                    "recommendation": "应用服务只编排事务和端口调用；核心业务规则下沉到聚合、领域服务、Policy 或 Specification。",
                    "suggested_code": '''PaymentDecision decision = settlementPolicy.decide(payment, command);
payment.applySettlementDecision(decision);''',
                }
            )
        elif group in {"REPO", "INFRA", "LAYER"}:
            remediation.update(
                {
                    "title": "领域层与基础设施边界被污染",
                    "recommendation": "领域接口使用业务类型，基础设施类型留在 adapter/infra 层，并通过 mapper/ACL 转换。",
                    "suggested_code": '''Optional<Payment> find(PaymentId paymentId);
PaymentEntity entity = paymentMapper.toEntity(payment);''',
                }
            )
        elif group == "EVENT":
            remediation.update(
                {
                    "title": "领域事件语义或发布一致性不清",
                    "recommendation": "事件命名为已发生事实，携带 ID/快照，并通过 outbox 或事务后发布保证可靠投递。",
                    "suggested_code": '''paymentRepository.save(payment);
outboxRepository.saveAll(payment.pullDomainEvents());''',
                }
            )
        else:
            remediation.update(
                {
                    "title": "DDD 领域规则表达不完整",
                    "recommendation": "用限界上下文、值对象、聚合方法、领域事件或策略对象显式表达业务语义，避免让调用方或基础设施承担领域规则。",
                    "suggested_code": '''Payment payment = Payment.create(command.paymentId(), command.money());
payment.apply(policy.evaluate(command));''',
                }
            )
    if category == "SPEL_INJECTION":
        remediation.update(
            {
                "title": "SpEL 表达式执行暴露完整 EvaluationContext",
                "recommendation": "禁止用用户可控表达式配合 StandardEvaluationContext 执行业务对象；改为白名单表达式、SimpleEvaluationContext 或显式策略枚举。",
                "suggested_code": '''ExpressionParser parser = new SpelExpressionParser();
SimpleEvaluationContext context = SimpleEvaluationContext
    .forReadOnlyDataBinding()
    .build();
Boolean matched = parser.parseExpression(allowedExpression)
    .getValue(context, safePolicyView, Boolean.class);''',
            }
        )
    elif category == "UNSAFE_REFLECTION":
        remediation.update(
            {
                "title": "外部可控类名进入反射加载",
                "recommendation": "不要直接使用请求参数调用 Class.forName/newInstance；改为服务端白名单插件注册表或策略枚举，并对插件失败执行 fail closed。",
                "suggested_code": '''RiskPlugin plugin = pluginRegistry.requireAllowed(pluginId);
RiskDecision decision = plugin.evaluate(safePolicyContext);
if (decision.failed()) {
    return RiskDecision.deny("PLUGIN_FAILED");
}''',
            }
        )
    elif category == "FAILURE_DEFAULT_ALLOW":
        remediation.update(
            {
                "title": "安全或风控失败时默认放行",
                "recommendation": "安全、风控、策略插件失败时应 fail closed，并记录可观测事件；只有经过审批的显式降级策略才能放行。",
                "suggested_code": '''try {
    return policyPlugin.evaluate(command);
} catch (PolicyPluginException e) {
    auditLogger.warn("policy plugin failed, fail closed requestId={}", command.requestId(), e);
    return PolicyDecision.deny("POLICY_PLUGIN_FAILED");
}''',
            }
        )
    elif category == "UNSAFE_DESERIALIZATION":
        remediation.update(
            {
                "title": "使用 ObjectInputStream 反序列化不可信对象",
                "recommendation": "不要在接口中接收 Java 原生序列化对象；改用 JSON DTO + Bean Validation，或至少配置 ObjectInputFilter 和命令白名单。",
                "suggested_code": '''ObjectInputFilter filter = ObjectInputFilter.Config.createFilter(
    "com.example.payment.SafeCommand;java.base/*;!*"
);
try (ObjectInputStream input = new ObjectInputStream(stream)) {
    input.setObjectInputFilter(filter);
    SafeCommand command = (SafeCommand) input.readObject();
}''',
            }
        )
    elif category == "ZIP_SLIP":
        remediation.update(
            {
                "title": "ZIP 解压写文件缺少路径归一化保护",
                "recommendation": "解压每个 entry 前必须 normalize 并校验仍在目标目录内，同时拒绝 symlink、特殊文件和目录穿越。",
                "suggested_code": '''Path target = outputDir.resolve(entry.getName()).normalize();
if (!target.startsWith(outputDir) || Files.isSymbolicLink(target)) {
    throw new SecurityException("invalid zip entry: " + entry.getName());
}
Files.copy(zipInputStream, target, StandardCopyOption.REPLACE_EXISTING);''',
            }
        )
    elif category == "ARCHIVE_BOMB_RISK":
        remediation.update(
            {
                "title": "压缩包处理缺少大小和条目数量限制",
                "recommendation": "处理 ZIP/TAR 时限制最大 entry 数、单文件大小、总解压字节和压缩比，超过阈值立即终止。",
                "suggested_code": '''long totalBytes = 0;
int entryCount = 0;
while ((entry = zip.getNextEntry()) != null) {
    if (++entryCount > maxEntries) throw new BadRequestException("too many entries");
    totalBytes += copyWithLimit(zip, target, maxEntryBytes);
    if (totalBytes > maxTotalBytes) throw new BadRequestException("archive too large");
}''',
            }
        )
    elif category == "REGEX_DOS":
        remediation.update(
            {
                "title": "用户可控正则存在 ReDoS 风险",
                "recommendation": "不要直接编译用户输入正则；改用 contains/equals/前缀匹配，或限制正则长度、语法和执行时间。",
                "suggested_code": '''String keyword = request.filter();
if (keyword.length() > 64) {
    throw new BadRequestException("filter too long");
}
boolean matched = customerId.contains(keyword);''',
            }
        )
    elif category == "CSV_OUTPUT_INJECTION":
        remediation.update(
            {
                "title": "CSV 输出未做单元格转义",
                "recommendation": "使用 CSV 库处理逗号、引号、换行和公式前缀字符，禁止手写字符串拼接生成 CSV。",
                "suggested_code": '''try (CSVPrinter printer = new CSVPrinter(writer, CSVFormat.DEFAULT)) {
    printer.printRecord(
        safeCsvCell(record.account()),
        safeCsvCell(record.amount().toPlainString())
    );
}''',
            }
        )
    elif category == "UNSAFE_FILE_RESPONSE":
        remediation.update(
            {
                "title": "下载响应文件名未净化",
                "recommendation": "Content-Disposition filename 必须净化路径分隔符、控制字符、长度和编码，避免响应头注入或路径信息泄漏。",
                "suggested_code": '''String safeName = filename.replaceAll("[\\\\r\\\\n/\\\\\\\\]", "_");
ContentDisposition disposition = ContentDisposition.attachment()
    .filename(safeName, StandardCharsets.UTF_8)
    .build();
headers.setContentDisposition(disposition);''',
            }
        )
    elif category == "ZIP_ENTRY_MKDIRS_IGNORED":
        remediation.update(
            {
                "title": "解压目录创建失败未中止写入",
                "recommendation": "检查 mkdirs/createDirectories 的结果和异常，目录不可用时立即失败，避免在错误路径继续写文件。",
                "suggested_code": '''Path parent = target.getParent();
try {
    Files.createDirectories(parent);
} catch (IOException e) {
    throw new BadRequestException("cannot create extraction directory", e);
}''',
            }
        )
    elif category == "ZIP_STREAM_RESOURCE_LEAK":
        remediation.update(
            {
                "title": "ZipInputStream 未使用 try-with-resources 关闭",
                "recommendation": "所有归档输入流必须放入 try-with-resources，确保异常路径也能关闭底层请求流和解压流。",
                "suggested_code": '''try (ZipInputStream zip = new ZipInputStream(request.getInputStream())) {
    ZipEntry entry;
    while ((entry = zip.getNextEntry()) != null) {
        handleEntry(zip, entry);
    }
}''',
            }
        )
    elif category == "DEFAULT_CHARSET_IO":
        remediation.update(
            {
                "title": "文件或 CSV 输出使用平台默认字符集",
                "recommendation": "跨平台导出必须显式指定 StandardCharsets.UTF_8，避免 Windows/Linux 默认编码不同导致内容损坏。",
                "suggested_code": '''byte[] bytes = csv.toString().getBytes(StandardCharsets.UTF_8);
Files.writeString(outputPath, csv.toString(), StandardCharsets.UTF_8);''',
            }
        )
    elif category == "AUDIT_TIME_ZONE":
        remediation.update(
            {
                "title": "审计或导出时间缺少显式 Clock/时区",
                "recommendation": "审计、结算和导出时间应使用注入的 Clock 与 Instant/ZoneId，保证跨区域和测试场景一致。",
                "suggested_code": '''private final Clock clock;

Instant exportedAt = Instant.now(clock);
String exportedDate = DateTimeFormatter.ISO_OFFSET_DATE_TIME
    .withZone(ZoneId.of("Asia/Shanghai"))
    .format(exportedAt);''',
            }
        )
    elif category == "PREDICTABLE_TEMP_FILE":
        remediation.update(
            {
                "title": "临时文件名可预测导致覆盖或数据泄露",
                "recommendation": "不要用商户、用户或固定前缀拼接临时文件；使用 Files.createTempFile，限制权限并在请求结束后清理。",
                "suggested_code": '''Path tempFile = Files.createTempFile("settlement-", ".csv");
try {
    Files.writeString(tempFile, csv, StandardCharsets.UTF_8);
} finally {
    Files.deleteIfExists(tempFile);
}''',
            }
        )
    if rule_id == "DEP-CVE-001":
        suggested_code = dependency_suggested_code_from_observation(observation)
        if suggested_code:
            remediation["suggested_code"] = suggested_code
    return remediation


def _drop_without_tool_support(finding: dict[str, Any], source_observations: list[dict[str, Any]]) -> bool:
    category = _selection_category_key(finding)
    if _is_low_precision_layer_finding(finding):
        return True
    if _is_low_precision_ddd_context_finding(finding, source_observations):
        return True
    if _is_low_precision_unbacked_advisory(finding, source_observations):
        return True
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
    registry_rule = rule_for_tool_observation(observation)
    if isinstance(registry_rule, dict) and registry_rule.get("promote_from_tool"):
        return str(registry_rule.get("id") or "")
    if raw_rule in PROMOTABLE_TOOL_RULES:
        return raw_rule
    if raw_rule in PROMOTABLE_EXTERNAL_TOOL_RULES:
        return PROMOTABLE_EXTERNAL_TOOL_RULES[raw_rule]
    category = normalized_rule_category(raw_rule, observation.get("message"))
    primary = CATEGORY_PRIMARY_RULE.get(category, "")
    if primary in PROMOTABLE_TOOL_RULES:
        return primary
    return ""


def _tool_promotion_threshold(rule_id: str, observation: dict[str, Any]) -> float:
    source_match = tool_source_for_observation(observation)
    source_threshold = 0.0
    if isinstance(source_match, dict) and str((source_match.get("rule") or {}).get("id") or "") == rule_id:
        source = source_match.get("source") or {}
        if isinstance(source, dict):
            try:
                source_threshold = float(source.get("min_confidence") or 0)
            except (TypeError, ValueError):
                source_threshold = 0.0
    tool_name = str(observation.get("tool_name") or "").strip().lower()
    return max(source_threshold, OSS_TOOL_PROMOTION_THRESHOLDS.get(tool_name, 0.85))


def _promotable_tool_observation(observation: dict[str, Any]) -> bool:
    rule_id = _canonical_tool_rule_id(observation)
    if rule_id not in PROMOTABLE_TOOL_RULES:
        return False
    if rule_id.startswith("DDD-"):
        path = str(observation.get("file_path") or "").replace("\\", "/").lower()
        message = str(observation.get("message") or "").lower()
        has_ddd_context = any(marker in path for marker in ["/domain/", "/application/", "/service/", "/repository/", "/event/"]) or any(
            marker in message
            for marker in [
                "domain model",
                "aggregate",
                "value object",
                "bounded context",
                "repository",
                "infrastructure",
                "persistence",
                "interface layer",
                "layer",
                "领域模型",
                "聚合",
                "值对象",
                "限界上下文",
                "仓储",
                "基础设施",
                "持久化",
                "接口层",
                "分层",
            ]
        )
        if not has_ddd_context:
            return False
    has_location = bool(observation.get("file_path")) and _as_int(observation.get("line_start")) is not None
    if not has_location:
        return False
    try:
        confidence = float(observation.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return confidence >= _tool_promotion_threshold(rule_id, observation)


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


def _tool_observation_group_key(rule_id: str, observation: dict[str, Any]) -> tuple[str, str, str, str, int]:
    raw_rule = canonical_rule_id(observation.get("rule_id"))
    artifact = str(observation.get("raw_artifact_id") or "")
    return (
        rule_id,
        raw_rule,
        str(observation.get("file_path") or ""),
        artifact,
        line_bucket(_as_int(observation.get("line_start"))),
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
    *,
    allowed_agent_ids: set[str] | None = None,
    allowed_rule_ids: set[str] | None = None,
    rule_agent_overrides: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    existing_keys = {_dedupe_key(item) for item in existing_findings}
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    group_rule: dict[tuple[str, str, str, str], str] = {}
    for observation in tool_observations:
        raw_rule_id = canonical_rule_id(observation.get("rule_id"))
        rule_id = raw_rule_id if allowed_rule_ids is not None and raw_rule_id in allowed_rule_ids else _canonical_tool_rule_id(observation)
        is_allowed_bound_rule = allowed_rule_ids is not None and rule_id in allowed_rule_ids
        if not is_allowed_bound_rule and not _promotable_tool_observation(observation):
            continue
        if is_allowed_bound_rule:
            has_location = bool(observation.get("file_path")) and _as_int(observation.get("line_start")) is not None
            if not has_location or float(observation.get("confidence") or 0) < 0.75:
                continue
        if allowed_rule_ids is not None and rule_id not in allowed_rule_ids:
            continue
        agent_id = (rule_agent_overrides or {}).get(rule_id) or _agent_for_rule(rule_id)
        if allowed_agent_ids is not None and agent_id not in allowed_agent_ids:
            continue
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
                "agent_id": (rule_agent_overrides or {}).get(rule_id) or _agent_for_rule(rule_id),
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
        if allowed_rule_ids is not None:
            scoped_rules = [rule for rule in (candidate.get("covered_rules") or []) if str(rule) in allowed_rule_ids]
            if not scoped_rules:
                continue
            candidate["covered_rules"] = scoped_rules
        candidate["dedupe_hash"] = sha1(
            "|".join(
                [
                    "tool-promoted",
                    *(str(item) for item in group_key),
                    str(line_bucket(line_start)),
                    evidence[:240],
                ]
            )
        )
        exact_existing = any(
            str(existing.get("file_path") or "") == str(candidate.get("file_path") or "")
            and abs((_as_int(existing.get("line_start")) or 0) - (line_start or 0)) <= 3
            and rule_id in {str(rule) for rule in (existing.get("covered_rules") or [])}
            and _finding_is_rule_specific(existing, rule_id)
            for existing in existing_findings
        )
        if exact_existing:
            continue
        key = _dedupe_key(candidate)
        existing_keys.add(key)
        promoted.append(candidate)
    return promoted


def _bound_rule_text(rule: dict[str, Any]) -> str:
    fields = [
        rule.get("rule_id"),
        rule.get("title"),
        rule.get("category"),
        rule.get("check"),
        rule.get("required_evidence"),
        rule.get("evidence_required"),
        rule.get("negative_examples"),
        rule.get("false_positive_patterns"),
    ]
    return "\n".join(str(value or "") for value in fields)


def _bound_rule_title(rule: dict[str, Any]) -> str:
    return str(rule.get("title") or rule.get("rule_id") or "绑定规范命中").strip()


def _bound_rule_severity(rule: dict[str, Any]) -> str:
    severity = str(rule.get("severity") or "medium").lower()
    return severity if severity in SEVERITY_RANK else "medium"


def _bound_rule_fix_guidance(rule: dict[str, Any]) -> str:
    return str(rule.get("fix_guidance") or rule.get("recommendation") or "按绑定规范要求修复，并补充对应回归验证。").strip()


def _existing_covered_rule_ids(findings: list[dict[str, Any]]) -> set[str]:
    covered: set[str] = set()
    for finding in findings:
        normalized = normalize_tool_finding(finding)
        for rule in normalized.get("covered_rules") or []:
            if rule:
                covered.add(str(rule))
    return covered


def _changed_file_added_lines(changed: Any) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for line_no, text in extract_added_lines(str(getattr(changed, "patch", "") or "")):
        if line_no is not None:
            lines.append((int(line_no), text))
    return lines


def _snippet(lines: list[tuple[int, str]], start_index: int, end_index: int) -> str:
    return "\n".join(f"{line_no}: {text}" for line_no, text in lines[max(0, start_index) : min(len(lines), end_index + 1)])


def _resource_type_pattern(rule_text: str) -> re.Pattern[str] | None:
    resource_markers: list[str] = []
    marker_map = {
        "fileinputstream": "FileInputStream",
        "files.newinputstream": "Files\\.newInputStream",
        "inputstream": "[A-Za-z0-9_]*InputStream",
        "reader": "[A-Za-z0-9_]*Reader",
        "connection": "Connection",
        "resultset": "ResultSet",
        "statement": "Statement",
    }
    lowered = rule_text.lower()
    for marker, pattern in marker_map.items():
        if marker in lowered:
            resource_markers.append(pattern)
    if not resource_markers:
        return None
    return re.compile(r"\b(?:new\s+(?:" + "|".join(resource_markers) + r")|(?:Connection|ResultSet|Statement)\s+\w+\s*=)", re.IGNORECASE)


def _rule_mentions_unclosed_resource(rule_text: str) -> bool:
    lowered = rule_text.lower()
    return bool(
        ("try-with-resources" in lowered or "关闭" in lowered or "close" in lowered)
        and ("inputstream" in lowered or "reader" in lowered or "connection" in lowered or "resultset" in lowered or "statement" in lowered)
    )


def _resource_line_has_owner_close(lines: list[tuple[int, str]], index: int) -> bool:
    current = lines[index][1]
    if "try (" in current or "try(" in current:
        return True
    window = "\n".join(text for _, text in lines[max(0, index - 2) : min(len(lines), index + 9)]).lower()
    return ".close(" in window or "try (" in window or "try(" in window


def _supplement_resource_rule(
    *,
    rule: dict[str, Any],
    agent_id: str,
    file_path: str,
    lines: list[tuple[int, str]],
) -> list[dict[str, Any]]:
    rule_text = _bound_rule_text(rule)
    pattern = _resource_type_pattern(rule_text)
    if pattern is None or not _rule_mentions_unclosed_resource(rule_text):
        return []
    findings: list[dict[str, Any]] = []
    for index, (line_no, text) in enumerate(lines):
        if not pattern.search(text) or _resource_line_has_owner_close(lines, index):
            continue
        rule_id = str(rule.get("rule_id") or "")
        evidence = (
            f"line {line_no}: {text.strip()}\n"
            f"绑定规范证据要求：{rule.get('required_evidence') or rule.get('evidence_required') or '展示资源创建行和关闭责任。'}"
        )
        findings.append(
            normalize_tool_finding(
                {
                    "severity": _bound_rule_severity(rule),
                    "confidence": 0.82,
                    "agent_id": agent_id,
                    "file_path": file_path,
                    "line_start": line_no,
                    "line_end": line_no,
                    "title": _bound_rule_title(rule),
                    "problem_description": "绑定规范要求新增资源必须由当前作用域关闭；该新增行创建了资源，但附近未看到 try-with-resources 或 close。",
                    "recommendation": _bound_rule_fix_guidance(rule),
                    "suggested_code": "try (var resource = /* create resource */) {\n    // use resource\n}",
                    "evidence": evidence,
                    "covered_rules": [rule_id],
                    "skipped_rules": [],
                    "judge_adjustment": "supplemented_from_bound_rule_document",
                    "verification_flags": ["bound_rule_document_supplement"],
                }
            )
        )
    return findings[:1]


def _rule_mentions_collection_mutation(rule_text: str) -> bool:
    lowered = rule_text.lower()
    return bool(
        ("for (" in lowered or "增强 for" in lowered or "foreach" in lowered)
        and (".remove" in lowered or ".add" in lowered or ".clear" in lowered or "修改集合" in lowered)
    )


def _supplement_collection_mutation_rule(
    *,
    rule: dict[str, Any],
    agent_id: str,
    file_path: str,
    lines: list[tuple[int, str]],
) -> list[dict[str, Any]]:
    if not _rule_mentions_collection_mutation(_bound_rule_text(rule)):
        return []
    findings: list[dict[str, Any]] = []
    for index, (line_no, text) in enumerate(lines):
        loop = re.search(r"\bfor\s*\([^:;]+?\b([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)", text)
        if not loop:
            continue
        collection_name = loop.group(2)
        block_end = min(len(lines), index + 12)
        for edit_line_no, edit_text in lines[index + 1 : block_end]:
            if re.search(rf"\b{re.escape(collection_name)}\s*\.\s*(remove|add|clear)\s*\(", edit_text):
                rule_id = str(rule.get("rule_id") or "")
                evidence = (
                    f"line {line_no}: {text.strip()}\n"
                    f"line {edit_line_no}: {edit_text.strip()}\n"
                    f"绑定规范证据要求：{rule.get('required_evidence') or rule.get('evidence_required') or '展示循环声明行和集合修改行。'}"
                )
                findings.append(
                    normalize_tool_finding(
                        {
                            "severity": _bound_rule_severity(rule),
                            "confidence": 0.84,
                            "agent_id": agent_id,
                            "file_path": file_path,
                            "line_start": edit_line_no,
                            "line_end": edit_line_no,
                            "title": _bound_rule_title(rule),
                            "problem_description": "绑定规范禁止在增强 for 遍历原集合时直接修改该集合；该代码在循环体内调用了原集合的修改方法。",
                            "recommendation": _bound_rule_fix_guidance(rule),
                            "suggested_code": f"{collection_name}.removeIf(item -> /* condition */);",
                            "evidence": evidence,
                            "covered_rules": [rule_id],
                            "skipped_rules": [],
                            "judge_adjustment": "supplemented_from_bound_rule_document",
                            "verification_flags": ["bound_rule_document_supplement"],
                        }
                    )
                )
                break
    return findings[:1]


def _code_anchor_tokens(rule: dict[str, Any]) -> set[str]:
    negative = str(rule.get("negative_examples") or "")
    check = str(rule.get("check") or "")
    raw_tokens = set(re.findall(r"`([^`\n]{2,120})`", f"{negative}\n{check}"))
    raw_tokens.update(re.findall(r"\b[A-Z][A-Za-z0-9_]{3,}\b", f"{negative}\n{check}"))
    raw_tokens.update(re.findall(r"\.[A-Za-z_][A-Za-z0-9_]*\s*\(", f"{negative}\n{check}"))
    tokens: set[str] = set()
    stop = {"String", "List", "Map", "Object", "Order", "PaymentOrder"}
    for token in raw_tokens:
        compact = token.strip()
        if not compact or compact in stop:
            continue
        nested_calls = re.findall(r"\.[A-Za-z_][A-Za-z0-9_]*\s*\(", compact)
        for nested in nested_calls:
            tokens.add(nested.replace(" ", ""))
        class_names = re.findall(r"\b[A-Z][A-Za-z0-9_]{3,}\b", compact)
        for class_name in class_names:
            if class_name not in stop:
                tokens.add(class_name)
        if len(compact) >= 3:
            tokens.add(compact)
    return tokens


def _has_specific_code_anchor_match(matched: list[str], window: str) -> bool:
    if any(token.startswith(".") or "(" in token for token in matched):
        return True
    lowered = window.lower()
    if re.search(r"\b(?:repository|mapper|gateway|client|dao|template)\s*\.\s*\w+\s*\(", window, re.I):
        return True
    if any(marker in lowered for marker in ["fileinputstream(", "newinputstream(", "executequery(", "executeupdate(", "readobject(", "parseexpression("]):
        return True
    return False


def _supplement_exact_anchor_rule(
    *,
    rule: dict[str, Any],
    agent_id: str,
    file_path: str,
    lines: list[tuple[int, str]],
) -> list[dict[str, Any]]:
    tokens = _code_anchor_tokens(rule)
    if len(tokens) < 2:
        return []
    findings: list[dict[str, Any]] = []
    for index, (line_no, text) in enumerate(lines):
        window_lines = lines[max(0, index - 2) : min(len(lines), index + 3)]
        window = "\n".join(item for _, item in window_lines)
        matched = [token for token in tokens if token in window]
        if len(matched) < min(3, len(tokens)):
            continue
        if not _has_specific_code_anchor_match(matched, window):
            continue
        scored_lines: list[tuple[int, int, int, str]] = []
        for candidate_line_no, candidate_text in window_lines:
            direct_matches = [token for token in matched if token in candidate_text]
            api_matches = [token for token in direct_matches if token.startswith(".") or "(" in token]
            scored_lines.append((len(api_matches), len(direct_matches), candidate_line_no, candidate_text))
        _, _, anchor_line_no, _ = max(scored_lines, key=lambda item: (item[0], item[1], item[2]))
        rule_id = str(rule.get("rule_id") or "")
        evidence = (
            f"{_snippet(lines, index - 2, index + 2)}\n"
            f"绑定规范证据要求：{rule.get('required_evidence') or rule.get('evidence_required') or '展示精确代码证据。'}"
        )
        findings.append(
            normalize_tool_finding(
                {
                    "severity": _bound_rule_severity(rule),
                    "confidence": 0.8,
                    "agent_id": agent_id,
                    "file_path": file_path,
                    "line_start": anchor_line_no,
                    "line_end": anchor_line_no,
                    "title": _bound_rule_title(rule),
                    "problem_description": "新增代码命中了绑定规范文档中的反例/API 锚点，需要按该规范修复。",
                    "recommendation": _bound_rule_fix_guidance(rule),
                    "suggested_code": "// 按绑定规范替换上述反例写法，并补充回归测试。",
                    "evidence": evidence,
                    "covered_rules": [rule_id],
                    "skipped_rules": [],
                    "judge_adjustment": "supplemented_from_bound_rule_document",
                    "verification_flags": ["bound_rule_document_supplement"],
                }
            )
        )
        break
    return findings[:1]


def supplement_bound_rule_findings(
    files: list[Any],
    selected_agents: list[dict[str, Any]],
    existing_findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_keys = {_dedupe_key(item) for item in existing_findings}
    added_lines_by_file = {str(getattr(changed, "filename", "") or ""): _changed_file_added_lines(changed) for changed in files}
    supplemented: list[dict[str, Any]] = []
    for agent in selected_agents:
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("agent_id") or "")
        if not agent_id:
            continue
        for rule in agent.get("bound_rules") or []:
            if not isinstance(rule, dict):
                continue
            rule_id = str(rule.get("rule_id") or "")
            if not rule_id:
                continue
            candidates: list[dict[str, Any]] = []
            for file_path, lines in added_lines_by_file.items():
                if not lines:
                    continue
                candidates.extend(_supplement_collection_mutation_rule(rule=rule, agent_id=agent_id, file_path=file_path, lines=lines))
                candidates.extend(_supplement_resource_rule(rule=rule, agent_id=agent_id, file_path=file_path, lines=lines))
                if not candidates:
                    candidates.extend(_supplement_exact_anchor_rule(rule=rule, agent_id=agent_id, file_path=file_path, lines=lines))
                if candidates:
                    break
            for candidate in candidates:
                key = _dedupe_key(candidate)
                if key in existing_keys:
                    continue
                candidate["dedupe_hash"] = sha1(
                    "|".join(
                        [
                            "bound-rule-supplement",
                            rule_id,
                            str(candidate.get("file_path") or ""),
                            str(candidate.get("line_start") or ""),
                            str(candidate.get("title") or ""),
                        ]
                    )
                )
                existing_keys.add(key)
                supplemented.append(candidate)
                break
    return supplemented


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


def _has_bound_authoritative_rule(finding: dict[str, Any]) -> bool:
    covered_rules = {str(rule) for rule in (finding.get("covered_rules") or []) if rule}
    bound_ids = _bound_authoritative_ids(finding)
    if any(bound_id and bound_id in covered_rules for bound_id in bound_ids):
        return True
    label = str(finding.get("review_batch_label") or "")
    return bool(label.startswith("bound_skill:") or label.startswith("bound_rule:"))


def _bound_authoritative_ids(finding: dict[str, Any]) -> set[str]:
    ids = {
        str(finding.get("checkpoint_id") or "").strip(),
        str(finding.get("bound_rule_id") or "").strip(),
    }
    label = str(finding.get("review_batch_label") or "").strip()
    if label.startswith("bound_rule:"):
        value = label.removeprefix("bound_rule:")
        if value.endswith(":coverage_retry"):
            value = value[: -len(":coverage_retry")]
        ids.add(value.split(":", 1)[0].strip())
    elif label.startswith("bound_skill:"):
        value = label.removeprefix("bound_skill:")
        if value.endswith(":coverage_retry"):
            value = value[: -len(":coverage_retry")]
        parts = value.split(":", 1)
        if len(parts) == 2:
            ids.add(parts[1].strip())
    return {item for item in ids if item}


def reconcile_rules_with_tool_observations(
    finding: dict[str, Any],
    source_observations: list[dict[str, Any]],
) -> dict[str, Any]:
    if not source_observations:
        return finding
    if _has_bound_authoritative_rule(finding):
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
    source_primary_rules: list[str] = []
    for observation in source_observations:
        canonical = _canonical_tool_rule_id(observation)
        if canonical:
            source_primary_rules.append(canonical)
            continue
        category = normalized_rule_category(str(observation.get("rule_id") or ""), observation.get("message"))
        primary = CATEGORY_PRIMARY_RULE.get(category, "")
        if primary:
            source_primary_rules.append(primary)
    source_primary_rules = sorted({rule for rule in source_primary_rules if rule in PROMOTABLE_TOOL_RULES})
    if source_primary_rules:
        filtered_exact = [rule for rule in covered_rules if rule in source_primary_rules]
        next_rules = filtered_exact or source_primary_rules
        if next_rules != covered_rules:
            item = dict(finding)
            normalized = normalize_tool_finding(item)
            normalized["covered_rules"] = next_rules
            normalized["rule_reconciliation"] = {
                "removed_rules": [rule for rule in covered_rules if rule not in next_rules],
                "source_categories": sorted(source_categories),
                "source_rules": source_primary_rules,
            }
            return normalized
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
    normalized = normalize_tool_finding(item)
    normalized["covered_rules"] = filtered_rules
    return normalized


def _best_source_observation_for_rule(
    source_observations: list[dict[str, Any]],
    rule_id: str,
) -> dict[str, Any] | None:
    for observation in source_observations:
        canonical = _canonical_tool_rule_id(observation)
        category = normalized_rule_category(str(observation.get("rule_id") or ""), observation.get("message"))
        if canonical == rule_id or CATEGORY_PRIMARY_RULE.get(category) == rule_id:
            return observation
    return None


def _has_code_null_signal(finding: dict[str, Any]) -> bool:
    text = _text_blob(finding)
    return ("string.valueof" in text and "payload.get" in text) or "literal \"null\"" in text or "字面量 \"null\"" in text


def align_finding_with_tool_observations(
    finding: dict[str, Any],
    source_observations: list[dict[str, Any]],
) -> dict[str, Any]:
    item = normalize_tool_finding(finding)
    covered = {str(rule) for rule in (item.get("covered_rules") or []) if rule}
    if "CODE-NULL-001" not in covered:
        return item

    observation = _best_source_observation_for_rule(source_observations, "CODE-NULL-001")
    be_api_observation = _best_source_observation_for_rule(source_observations, "BE-API-001") if "BE-API-001" in covered else None
    if not observation:
        return item
    observation_text = str(observation.get("message") or "")
    if "string.valueof" not in observation_text.lower() or "payload.get" not in observation_text.lower():
        return item

    remediation = RULE_REMEDIATION.get("CODE-NULL-001", {})
    aligned = dict(item)
    if not _has_code_null_signal(item):
        aligned["title"] = remediation.get("title") or "Map 入参字段缺少显式空值和类型校验"
        aligned["problem_description"] = (
            f"工具证据显示新增代码使用 {observation_text}；字段缺失时会得到字面量 \"null\"，"
            "绕过显式必填校验并进入后续查询或业务逻辑。"
        )
        aligned["evidence"] = observation_text
    aligned["recommendation"] = remediation.get("recommendation") or aligned.get("recommendation")
    aligned["suggested_code"] = remediation.get("suggested_code") or aligned.get("suggested_code")
    aligned["line_start"] = _as_int(observation.get("line_start")) or aligned.get("line_start")
    aligned["line_end"] = _as_int(observation.get("line_end")) or aligned.get("line_end") or aligned.get("line_start")
    aligned["tool_rule_id"] = "CODE-NULL-001"
    aligned["agent_id"] = _agent_for_rule("CODE-NULL-001")
    aligned["verification_flags"] = [*(aligned.get("verification_flags") or []), "aligned_to_tool_observation"]
    aligned["quality_trace"] = {
        **(aligned.get("quality_trace") if isinstance(aligned.get("quality_trace"), dict) else {}),
        "aligned_to_tool_rule": "CODE-NULL-001",
        "aligned_to_tool_line": aligned.get("line_start"),
    }
    if be_api_observation:
        be_api_text = str(be_api_observation.get("message") or "")
        if "@requestbody" in be_api_text.lower() and "@valid" in be_api_text.lower():
            be_api_sentence = f"同一入口还命中 BE-API-001：{be_api_text}"
            for key in ["problem_description", "evidence"]:
                current_text = str(aligned.get(key) or "")
                if "@valid" not in current_text.lower():
                    aligned[key] = f"{current_text}\n{be_api_sentence}".strip()
            flags = list(aligned.get("verification_flags") or [])
            if "aligned_to_be_api_validation_observation" not in flags:
                flags.append("aligned_to_be_api_validation_observation")
            aligned["verification_flags"] = flags
            aligned["quality_trace"] = {
                **(aligned.get("quality_trace") if isinstance(aligned.get("quality_trace"), dict) else {}),
                "aligned_to_be_api_rule": "BE-API-001",
                "aligned_to_be_api_line": _as_int(be_api_observation.get("line_start")) or aligned.get("line_start"),
            }
    return normalize_tool_finding(aligned)


def _has_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def build_evidence_contract(finding: dict[str, Any], source_observations: list[dict[str, Any]]) -> dict[str, Any]:
    rules = [str(rule) for rule in (finding.get("covered_rules") or []) if str(rule or "").strip()]
    explicit_rule = str(finding.get("tool_rule_id") or finding.get("rule_id") or "").strip()
    has_rule = bool(rules or re.fullmatch(r"[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+(?::[A-Z0-9_]+)?", explicit_rule))
    has_location = _has_text(finding.get("file_path")) and bool(_as_int(finding.get("line_start")))
    has_source_context = _has_text(finding.get("evidence")) or bool(source_observations)
    has_tool_evidence = bool(source_observations or _has_text(finding.get("tool_name")) or _has_text(finding.get("tool_rule_id")))
    has_recommendation = _has_text(finding.get("recommendation"))
    suggested_code = str(finding.get("suggested_code") or "").strip()
    has_suggested_code = bool(suggested_code and "未提供明确代码片段" not in suggested_code)
    has_agent_source = _has_text(finding.get("agent_id"))
    checks = {
        "has_rule": has_rule,
        "has_location": has_location,
        "has_source_context": has_source_context,
        "has_tool_evidence": has_tool_evidence,
        "has_recommendation": has_recommendation,
        "has_suggested_code": has_suggested_code,
    }
    missing = [name for name, passed in checks.items() if not passed]
    score = round(sum(1 for passed in checks.values() if passed) / len(checks), 4)
    has_publishable_agent_contract = (
        has_agent_source
        and has_rule
        and has_location
        and has_source_context
        and has_recommendation
        and has_suggested_code
    )
    if (score >= 0.84 and has_location and has_source_context and has_recommendation) or has_publishable_agent_contract:
        status = "satisfied"
    elif score >= 0.5 and has_location:
        status = "partial"
    else:
        status = "weak"
    source_type = "hybrid" if has_agent_source and has_tool_evidence else "tool" if has_tool_evidence else "agent" if has_agent_source else "unknown"
    decision_hint = "final_candidate" if status == "satisfied" else "needs_review" if status == "weak" else "advisory_candidate"
    return {
        "version": "evidence_contract_v1",
        **checks,
        "missing": missing,
        "score": score,
        "status": status,
        "source_type": source_type,
        "decision_hint": decision_hint,
        "evidence_sources": [
            source
            for source, present in {
                "rule": has_rule,
                "location": has_location,
                "source_context": has_source_context,
                "tool": has_tool_evidence,
                "recommendation": has_recommendation,
                "suggested_code": has_suggested_code,
            }.items()
            if present
        ],
    }


def build_quality_trace(finding: dict[str, Any], source_observations: list[dict[str, Any]]) -> dict[str, Any]:
    merged_agent_ids = [
        str(agent_id)
        for agent_id in (finding.get("merged_agent_ids") or [finding.get("agent_id")])
        if str(agent_id or "").strip()
    ]
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
        "merged_agent_ids": merged_agent_ids,
        "consensus_agents": merged_agent_ids,
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
        "evidence_contract": build_evidence_contract(finding, source_observations),
        "bound_evidence_contract": finding.get("bound_evidence_contract") or {},
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


def _has_structured_agent_evidence(finding: dict[str, Any]) -> bool:
    if _is_tool_backed_finding(finding):
        return False
    has_agent = _has_text(finding.get("agent_id"))
    has_location = _has_text(finding.get("file_path")) and bool(_as_int(finding.get("line_start")))
    has_rule = bool([rule for rule in (finding.get("covered_rules") or []) if str(rule or "").strip()] or _has_text(finding.get("rule_id")) or _has_text(finding.get("tool_rule_id")))
    has_problem = _has_text(finding.get("title")) and (_has_text(finding.get("problem_description")) or _has_text(finding.get("evidence")))
    has_recommendation = _has_text(finding.get("recommendation"))
    try:
        confidence = float(finding.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return has_agent and has_location and has_rule and has_problem and has_recommendation and confidence >= 0.6


def should_retain_low_precision_without_tool_support(finding: dict[str, Any], source_observations: list[dict[str, Any]]) -> bool:
    if source_observations:
        return False
    if not _has_structured_agent_evidence(finding):
        return False
    covered = {str(rule) for rule in (finding.get("covered_rules") or []) if rule}
    if any(_looks_like_bound_document_rule(rule) for rule in covered):
        return True
    flags = {str(flag) for flag in (finding.get("verification_flags") or [])}
    if flags & {"bound_rule_document_supplement", "low_evidence_match", "source_location_supported", "source_window_missing"}:
        return True
    return bool(covered)


def retain_as_needs_review(
    finding: dict[str, Any],
    *,
    reason: str,
    quality_trace: dict[str, Any] | None = None,
    source_observations: list[dict[str, Any]] | None = None,
    tool_provenance: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    item = dict(finding)
    trace = quality_trace if isinstance(quality_trace, dict) else build_quality_trace(item, source_observations or [])
    trace_judge = trace.get("judge") if isinstance(trace.get("judge"), dict) else {}
    item["selected"] = 0
    item["judge_adjustment"] = f"needs_review:{reason}"
    item["quality_trace"] = {
        **trace,
        "judge": {
            **trace_judge,
            "selected": False,
            "adjustment": item["judge_adjustment"],
            "review_tier": "needs_review",
            "retained_reason": reason,
        },
    }
    item["verification_flags"] = [*(item.get("verification_flags") or []), "retained_for_human_review"]
    if source_observations is not None:
        item["source_observations"] = source_observations
    if tool_provenance is not None:
        item["tool_provenance"] = tool_provenance
    return item


def _is_needs_review_retained(finding: dict[str, Any]) -> bool:
    trace = finding.get("quality_trace") if isinstance(finding.get("quality_trace"), dict) else {}
    judge = trace.get("judge") if isinstance(trace.get("judge"), dict) else {}
    return str(judge.get("review_tier") or "") == "needs_review" or str(finding.get("judge_adjustment") or "").startswith("needs_review:")


def _critic_rejected(finding: dict[str, Any]) -> bool:
    trace = finding.get("quality_trace") if isinstance(finding.get("quality_trace"), dict) else {}
    verdict = trace.get("critic_verdict") if isinstance(trace.get("critic_verdict"), dict) else {}
    return str(verdict.get("verdict") or "") == "rejected"


def is_publishable_evidence_contract(quality_trace: dict[str, Any]) -> bool:
    contract = quality_trace.get("evidence_contract") if isinstance(quality_trace, dict) else None
    if not isinstance(contract, dict):
        return False
    return contract.get("status") == "satisfied" and contract.get("decision_hint") == "final_candidate"


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
    conn: Any,
    *,
    run_id: str,
    agent_id: str,
    observations: list[dict[str, Any]],
) -> None:
    for observation in observations:
        conn.execute(
            """
            UPDATE tool_observations
            SET adopted_by_agent = %s, adoption_state = 'adopted_final'
            WHERE review_run_id = %s
              AND tool_name = %s
              AND COALESCE(rule_id, '') = COALESCE(%s, '')
              AND file_path = %s
              AND COALESCE(line_start, -1) = COALESCE(%s, -1)
              AND message = %s
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


def _mark_observation_state(
    conn: Any,
    *,
    run_id: str,
    observation: dict[str, Any],
    state: str,
    agent_id: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE tool_observations
        SET adopted_by_agent = COALESCE(%s, adopted_by_agent),
            adoption_state = %s
        WHERE review_run_id = %s
          AND tool_name = %s
          AND COALESCE(rule_id, '') = COALESCE(%s, '')
          AND file_path = %s
          AND COALESCE(line_start, -1) = COALESCE(%s, -1)
          AND message = %s
        """,
        (
            agent_id,
            state,
            run_id,
            observation.get("tool_name"),
            observation.get("rule_id"),
            observation.get("file_path"),
            observation.get("line_start"),
            observation.get("message"),
        ),
    )


def _mark_promoted_rejection_sources(
    conn: Any,
    *,
    run_id: str,
    rejections: list[dict[str, Any]],
) -> None:
    for rejected in rejections:
        observation = rejected.get("source_tool_observation")
        if not isinstance(observation, dict):
            continue
        _mark_observation_state(
            conn,
            run_id=run_id,
            observation=observation,
            state="rejected_by_judge",
            agent_id=str(rejected.get("agent_id") or "") or None,
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
        if _is_weak_unbacked_ddd_design_finding(item):
            rejected.append({**item, "rejected_reasons": ["weak_unbacked_ddd_design_evidence"]})
            continue
        if item.get("dedupe_hash") in weak_high_severity_hashes and item.get("severity") in {"critical", "high"}:
            item["severity"] = "medium"
            item["judge_adjustment"] = "downgraded_high_severity_weak_evidence"
        key = _semantic_dedupe_key(item)
        current = by_key.get(key)
        if current is None:
            by_key[key] = _normalize_for_judging(item)
            continue
        current_exact_tool = _has_exact_promoted_tool_rule(current)
        item_exact_tool = _has_exact_promoted_tool_rule(item)
        if current_exact_tool != item_exact_tool:
            if item_exact_tool:
                rejected.append({**current, "rejected_reasons": ["deduped_lower_rank"]})
                by_key[key] = _merge_finding_metadata(_normalize_for_judging(item), current)
            else:
                rejected.append({**item, "rejected_reasons": ["deduped_lower_rank"]})
                by_key[key] = _merge_finding_metadata(current, item)
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
        threshold = _selection_threshold_for_finding(item, selection_confidence)
        item["selected"] = 1 if float(item.get("confidence") or 0) >= threshold and item.get("severity") in SELECTABLE_SEVERITIES else 0

    return selected, rejected


def make_judge_findings_node(
    *,
    conn: Any,
    recorder: Any,
    job: Any,
    project_id: str,
    run_id: str,
    new_id: Any,
    load_tool_observations: Any,
    project_config: dict[str, Any] | None = None,
    max_findings: int = 20,
    selection_confidence: float = 0.75,
):
    def load_suppression_hints() -> list[dict[str, Any]]:
        try:
            return [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT project_id, rule_id, file_glob, snippet_hash, snippet_excerpt, count, last_marked_at
                    FROM rule_suppression_hints
                    WHERE project_id = %s
                    """,
                    (project_id,),
                ).fetchall()
            ]
        except Exception:
            return []

    def judge_findings_node(state: dict[str, Any]) -> dict[str, Any]:
        judge_span = recorder.span("judge_findings")
        tool_observations = state.get("tool_observations") or load_tool_observations(conn, run_id)
        tool_observations, diff_rejected_observations = filter_tool_observations_to_added_lines(tool_observations, state.get("files") or [])
        for observation in diff_rejected_observations:
            _mark_observation_state(
                conn,
                run_id=run_id,
                observation=observation,
                state="rejected_not_on_diff",
            )
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
        selected_agents = state.get("selected_agents") or []
        selected_agent_ids = {str(agent.get("agent_id") or "") for agent in selected_agents if isinstance(agent, dict) and agent.get("agent_id")}
        bound_rule_agent_overrides: dict[str, str] = {}
        for agent in selected_agents:
            if not isinstance(agent, dict):
                continue
            agent_id = str(agent.get("agent_id") or "")
            if not agent_id:
                continue
            for rule in agent.get("bound_rules") or []:
                if isinstance(rule, dict) and rule.get("rule_id"):
                    bound_rule_agent_overrides[str(rule["rule_id"])] = agent_id
        promoted_findings = promote_tool_observations(
            tool_observations,
            state["verified_findings"],
            allowed_agent_ids=selected_agent_ids or None,
            allowed_rule_ids=set(bound_rule_agent_overrides) or None,
            rule_agent_overrides=bound_rule_agent_overrides or None,
        )
        if promoted_findings:
            upsert_candidate_findings(
                conn,
                review_run_id=run_id,
                items=promoted_findings,
                stage="tool_promotion",
                status="candidate",
            )
            recorder.event(
                judge_span,
                "tool_observations_promoted",
                f"采纳 {len(promoted_findings)} 个高置信工具观察作为候选问题",
                {
                    "rules": sorted({rule for item in promoted_findings for rule in item.get("covered_rules", [])}),
                    "tool_observation_count": len(tool_observations),
                },
            )
        supplemented_findings = supplement_bound_rule_findings(
            state.get("files") or [],
            selected_agents,
            [*state["verified_findings"], *promoted_findings],
        )
        if supplemented_findings:
            upsert_candidate_findings(
                conn,
                review_run_id=run_id,
                items=supplemented_findings,
                stage="bound_rule_supplement",
                status="candidate",
            )
            recorder.event(
                judge_span,
                "bound_rule_findings_supplemented",
                f"按绑定规范文档补充 {len(supplemented_findings)} 个候选问题",
                {
                    "rules": sorted({rule for item in supplemented_findings for rule in item.get("covered_rules", [])}),
                },
            )
        final_findings, judge_rejections = judge_candidate_findings(
            [*state["verified_findings"], *promoted_findings, *supplemented_findings],
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
            threshold = _selection_threshold_for_finding(item, selection_confidence)
            item["selected"] = 0 if "invalid_suggested_code" in flags else 1 if float(item.get("confidence") or 0) >= threshold and item.get("severity") in SELECTABLE_SEVERITIES else 0
        final_selected_findings: list[dict[str, Any]] = []
        for item in final_findings:
            if item.get("selected", 0):
                final_selected_findings.append(item)
                continue
            judge_rejections.append({**item, "rejected_reasons": ["not_selected_final_issue"]})
        final_findings = final_selected_findings
        final_findings, same_line_rejections = dedupe_same_line_same_issue_findings(final_findings)
        if same_line_rejections:
            judge_rejections.extend(same_line_rejections)
            recorder.event(
                judge_span,
                "finding_deduped",
                f"合并 {len(same_line_rejections)} 个同文件同行重复问题",
                {
                    "deduped_count": len(same_line_rejections),
                    "deduped_agents": sorted(
                        {
                            str(item.get("agent_id") or "")
                            for item in same_line_rejections
                            if item.get("agent_id")
                        }
                    ),
                },
            )
        final_findings, low_signal_rejections = _prune_low_signal_final_findings(final_findings)
        if low_signal_rejections:
            judge_rejections.extend(low_signal_rejections)
            recorder.event(
                judge_span,
                "finding_pruned",
                f"收敛 {len(low_signal_rejections)} 个低信号或已覆盖的最终问题",
                {
                    "reasons": sorted(
                        {
                            str(reason)
                            for item in low_signal_rejections
                            for reason in (item.get("rejected_reasons") or [])
                        }
                    ),
                },
            )
        before_fill_count = len(final_findings)
        final_findings = _fill_missing_tool_coverage(
            final_findings,
            tool_observations,
            max_findings=max_findings,
            allowed_agent_ids=selected_agent_ids or None,
        )
        if len(final_findings) > before_fill_count:
            recorder.event(
                judge_span,
                "finding_tool_coverage_filled",
                f"按高信号工具观测补齐 {len(final_findings) - before_fill_count} 个最终问题",
                {
                    "filled_count": len(final_findings) - before_fill_count,
                    "rules": sorted({rule for item in final_findings[before_fill_count:] for rule in item.get("covered_rules", [])}),
                },
            )
        for rejected in judge_rejections:
            upsert_candidate_finding(
                conn,
                review_run_id=run_id,
                item=rejected,
                stage="judge",
                status="rejected",
                rejected_reasons=rejected.get("rejected_reasons") or [],
            )
            reasons = rejected.get("rejected_reasons") or []
            recorder.event(
                judge_span,
                "finding_dropped",
                f"{rejected.get('title', 'candidate')} 被 Judge 过滤：{','.join(reasons)}",
                {"dedupe_hash": rejected.get("dedupe_hash"), "reasons": reasons},
            )
        _mark_promoted_rejection_sources(conn, run_id=run_id, rejections=judge_rejections)
        prepared_findings: list[dict[str, Any]] = []
        line_index = changed_line_index(state.get("files") or [])
        registry_defaults = load_registry().get("defaults", {})
        evidence_thresholds = registry_defaults.get("evidence_thresholds") if isinstance(registry_defaults, dict) else {}
        suppression_hints = load_suppression_hints()
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
            finding = align_finding_with_tool_observations(finding, source_observations)
            if _drop_without_tool_support(finding, source_observations):
                if should_retain_low_precision_without_tool_support(finding, source_observations):
                    tool_provenance = _tool_provenance(finding, source_observations)
                    retained = retain_as_needs_review(
                        finding,
                        reason="unsupported_low_precision_llm_finding",
                        quality_trace=build_quality_trace(finding, source_observations),
                        source_observations=source_observations,
                        tool_provenance=tool_provenance,
                    )
                    prepared_findings.append(retained)
                    recorder.event(
                        judge_span,
                        "finding_retained_for_review",
                        f"{finding.get('title', 'candidate')} 被保留为 needs_review：unsupported_low_precision_llm_finding",
                        {"dedupe_hash": finding.get("dedupe_hash"), "rules": finding.get("covered_rules") or []},
                    )
                    continue
                judge_rejections.append({**finding, "rejected_reasons": ["unsupported_low_precision_llm_finding"]})
                recorder.event(
                    judge_span,
                    "finding_dropped",
                    f"{finding.get('title', 'candidate')} 被 Judge 过滤：unsupported_low_precision_llm_finding",
                    {"dedupe_hash": finding.get("dedupe_hash"), "rules": finding.get("covered_rules") or []},
                )
                continue
            duplicate = next((item for item in prepared_findings if _duplicate_same_issue(item, finding)), None)
            if duplicate is not None:
                judge_rejections.append({**finding, "rejected_reasons": ["deduped_after_rule_reconciliation"]})
                recorder.event(
                    judge_span,
                    "finding_dropped",
                    f"{finding.get('title', 'candidate')} 被 Judge 过滤：deduped_after_rule_reconciliation",
                    {"dedupe_hash": finding.get("dedupe_hash"), "rules": finding.get("covered_rules") or []},
                )
                continue
            source_observations = [
                {**item, "adoption_state": "adopted_final", "adopted_by_agent": finding.get("agent_id")}
                for item in source_observations
            ]
            tool_provenance = _tool_provenance(finding, source_observations)
            quality_trace = build_quality_trace(finding, source_observations)
            evidence_score = score_evidence(
                finding,
                line_index=line_index,
                related_context=state.get("related_context") or {},
                tool_observations=tool_observations,
                source_observations=source_observations,
                peer_findings=final_findings,
                suppression_hints=suppression_hints,
            )
            finding = apply_evidence_score_policy(finding, evidence_score, evidence_thresholds if isinstance(evidence_thresholds, dict) else None)
            quality_trace = {
                **quality_trace,
                "evidence_score": evidence_score,
                "consensus_agents": evidence_score.get("consensus_agents") or [],
                "matched_suppression_hint": evidence_score.get("matched_suppression_hint"),
            }
            if finding.get("judge_adjustment") == "evidence_score_below_drop_threshold" and should_retain_low_precision_without_tool_support(finding, source_observations):
                finding = retain_as_needs_review(
                    finding,
                    reason="evidence_score_below_drop_threshold",
                    quality_trace=quality_trace,
                    source_observations=source_observations,
                    tool_provenance=tool_provenance,
                )
                prepared_findings.append(finding)
                recorder.event(
                    judge_span,
                    "finding_retained_for_review",
                    f"{finding.get('title', 'candidate')} 被保留为 needs_review：evidence_score_below_drop_threshold",
                    {"dedupe_hash": finding.get("dedupe_hash"), "evidence_score": evidence_score},
                )
                continue
            if not is_publishable_evidence_contract(quality_trace):
                contract = quality_trace.get("evidence_contract") if isinstance(quality_trace, dict) else {}
                if should_retain_low_precision_without_tool_support(finding, source_observations):
                    retained = retain_as_needs_review(
                        finding,
                        reason="evidence_contract_not_satisfied",
                        quality_trace=quality_trace,
                        source_observations=source_observations,
                        tool_provenance=tool_provenance,
                    )
                    prepared_findings.append(retained)
                    recorder.event(
                        judge_span,
                        "finding_retained_for_review",
                        f"{finding.get('title', 'candidate')} 被保留为 needs_review：evidence_contract_not_satisfied",
                        {
                            "dedupe_hash": finding.get("dedupe_hash"),
                            "contract_status": contract.get("status") if isinstance(contract, dict) else None,
                            "missing": contract.get("missing") if isinstance(contract, dict) else [],
                        },
                    )
                    continue
                rejected = {
                    **finding,
                    "quality_trace": quality_trace,
                    "source_observations": source_observations,
                    "tool_provenance": tool_provenance,
                    "rejected_reasons": ["evidence_contract_not_satisfied"],
                }
                judge_rejections.append(rejected)
                recorder.event(
                    judge_span,
                    "finding_dropped",
                    f"{finding.get('title', 'candidate')} 被 Judge 过滤：evidence_contract_not_satisfied",
                    {
                        "dedupe_hash": finding.get("dedupe_hash"),
                        "contract_status": contract.get("status") if isinstance(contract, dict) else None,
                        "missing": contract.get("missing") if isinstance(contract, dict) else [],
                    },
                )
                continue
            finding["source_observations"] = source_observations
            finding["tool_provenance"] = tool_provenance
            finding["quality_trace"] = quality_trace
            finding["evidence_score"] = evidence_score
            prepared_findings.append(finding)
        final_findings = run_critic_pass(
            findings=prepared_findings,
            source_file_contents=state.get("source_file_contents") or {},
            config=project_config or {},
            recorder=recorder,
            span_id=judge_span,
            budget_tracker=state.get("budget_tracker"),
        )
        quality_selected_findings: list[dict[str, Any]] = []
        for finding in final_findings:
            if _critic_rejected(finding):
                rejected = {**finding, "rejected_reasons": ["critic_rejected"]}
                judge_rejections.append(rejected)
                recorder.event(
                    judge_span,
                    "finding_dropped",
                    f"{finding.get('title', 'candidate')} 被 Judge 过滤：critic_rejected",
                    {"dedupe_hash": finding.get("dedupe_hash"), "critic_verdict": finding.get("quality_trace", {}).get("critic_verdict") if isinstance(finding.get("quality_trace"), dict) else None},
                )
                continue
            if _is_needs_review_retained(finding):
                quality_selected_findings.append(finding)
                continue
            if not bool(finding.get("selected", 1)) or finding.get("judge_adjustment") == "evidence_score_below_drop_threshold":
                rejected = {**finding, "rejected_reasons": ["evidence_score_below_drop_threshold"]}
                judge_rejections.append(rejected)
                recorder.event(
                    judge_span,
                    "finding_dropped",
                    f"{finding.get('title', 'candidate')} 被 Judge 过滤：evidence_score_below_drop_threshold",
                    {
                        "dedupe_hash": finding.get("dedupe_hash"),
                        "evidence_score": finding.get("evidence_score"),
                        "judge_adjustment": finding.get("judge_adjustment"),
                    },
                )
                continue
            if str(finding.get("severity") or "") in SELECTABLE_SEVERITIES:
                quality_selected_findings.append(finding)
                continue
            rejected = {**finding, "rejected_reasons": ["not_selected_after_quality_calibration"]}
            judge_rejections.append(rejected)
            recorder.event(
                judge_span,
                "finding_dropped",
                f"{finding.get('title', 'candidate')} 被 Judge 过滤：not_selected_after_quality_calibration",
                {"dedupe_hash": finding.get("dedupe_hash"), "severity": finding.get("severity")},
            )
        final_findings = quality_selected_findings
        persisted_findings: list[dict[str, Any]] = []
        for finding in final_findings:
            source_observations = finding.get("source_observations") or []
            tool_provenance = finding.get("tool_provenance") or []
            quality_trace = finding.get("quality_trace") if isinstance(finding.get("quality_trace"), dict) else {}
            evidence_score = finding.get("evidence_score") if isinstance(finding.get("evidence_score"), dict) else {}
            finding_id = new_id("finding")
            conn.execute(
                """
                INSERT INTO review_findings (
                  id, review_run_id, severity, confidence, agent_id, head_sha, dedupe_hash,
                  file_path, line_start, line_end, title, problem_description, recommendation, suggested_code, evidence,
                  covered_rules_json, skipped_rules_json, tool_provenance_json, source_observations_json, quality_trace_json,
                  evidence_score_json,
                  publish_state, lifecycle_state, selected
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', 'pending', %s)
                """,
                (
                    finding_id,
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
                    json.dumps(evidence_score, ensure_ascii=False),
                    int(finding.get("selected", 0)),
                ),
            )
            finding["persisted_finding_id"] = finding_id
            upsert_candidate_finding(
                conn,
                review_run_id=run_id,
                item=finding,
                stage="judge",
                status="final",
                final_finding_id=finding_id,
            )
            _mark_observations_adopted(
                conn,
                run_id=run_id,
                agent_id=str(finding.get("agent_id") or ""),
                observations=source_observations,
            )
            persisted_findings.append(finding)
        final_findings = persisted_findings
        _mark_promoted_rejection_sources(conn, run_id=run_id, rejections=judge_rejections)
        for rejected in judge_rejections:
            upsert_candidate_finding(
                conn,
                review_run_id=run_id,
                item=rejected,
                stage="judge",
                status="rejected",
                rejected_reasons=rejected.get("rejected_reasons") or [],
            )
        conn.commit()
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
        verifier_rejections = state.get("verifier_rejections") or []
        return {
            **state,
            "final_findings": final_findings,
            "judge_rejections": judge_rejections,
            "candidate_rejections": [*verifier_rejections, *judge_rejections],
            "candidate_quality": {
                **(state.get("candidate_quality") or {}),
                "tool_observation_count": len(tool_observations),
                "tool_observation_rejected_not_on_diff_count": len(diff_rejected_observations),
                "promoted_tool_candidate_count": len(promoted_findings),
                "judge_rejected_count": len(judge_rejections),
                "final_finding_count": len(final_findings),
                "candidate_rejected_count": len(verifier_rejections) + len(judge_rejections),
            },
        }

    return judge_findings_node
