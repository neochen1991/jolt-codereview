from __future__ import annotations

import hashlib
import re
from typing import Any


RULE_CATEGORY_MAP = {
    "SQL_INJECTION_JDBC": "SQL_INJECTION",
    "java.lang.security.audit.sqli.jdbc-sqli": "SQL_INJECTION",
    "SpringInjection": "SQL_INJECTION",
    "SEC-INJECT-003": "SQL_INJECTION",
    "JOLT_JAVA_SQL_CONCAT": "SQL_INJECTION",
    "JOLT_JAVA_MISSING_VALID": "SPRING_VALIDATION",
    "jolt.java.spring.missing-valid-request-body": "SPRING_VALIDATION",
    "BE-API-001": "SPRING_VALIDATION",
    "JOLT_JAVA_MISSING_TRANSACTION": "SPRING_TRANSACTION",
    "BE-TX-002": "SPRING_TRANSACTION",
    "JOLT_JAVA_REDIS_KEYS": "REDIS_DANGEROUS_COMMAND",
    "jolt.java.redis.keys": "REDIS_DANGEROUS_COMMAND",
    "REDIS-CMD-003": "REDIS_DANGEROUS_COMMAND",
    "JOLT_JAVA_REDIS_MISSING_TTL": "REDIS_MISSING_TTL",
    "jolt.java.redis.set-without-ttl": "REDIS_MISSING_TTL",
    "REDIS-TTL-002": "REDIS_MISSING_TTL",
    "JOLT_JAVA_HARDCODED_SECRET": "SECRET_LEAK",
    "jolt.hardcoded-password": "SECRET_LEAK",
    "jolt.config.hardcoded-password": "SECRET_LEAK",
    "jolt.java.sensitive-payment-field": "SECRET_LEAK",
    "jolt.java.sensitive-response-field": "SECRET_LEAK",
    "jolt.java.sensitive-data-logging": "SECRET_LEAK",
    "jolt.java.sensitive-audit-write": "SECRET_LEAK",
    "jolt.config.jpa-show-sql-enabled": "CONFIG_SQL_LOGGING",
    "SEC-SECRET-004": "SECRET_LEAK",
    "JOLT_JAVA_EXCEPTION_MESSAGE_RESPONSE": "ERROR_INFORMATION_LEAK",
    "jolt.java.stacktrace-response": "ERROR_INFORMATION_LEAK",
    "jolt.config.stacktrace-enabled": "ERROR_INFORMATION_LEAK",
    "SEC-SECRET-004:ERROR_RESPONSE": "ERROR_INFORMATION_LEAK",
    "jolt.java.admin-mutation-endpoint": "AUTHORIZATION_BYPASS",
    "jolt.java.client-controlled-risk-bypass": "RISK_CONTROL_BYPASS",
    "jolt.java.weak-webhook-signature-match": "WEAK_WEBHOOK_TRUST",
    "jolt.java.webhook-dedupe-key-composite-change": "IDEMPOTENCY_GUARD",
    "jolt.java.untrusted-callback-url-invocation": "SSRF_CALLBACK",
    "jolt.java.signature-string-equals": "WEAK_SIGNATURE_COMPARE",
    "jolt.java.spring-debug-endpoint-method": "DEBUG_ENDPOINT_EXPOSURE",
    "jolt.java.trust-x-forwarded-for": "UNTRUSTED_FORWARDED_HEADER",
    "config.static-rules.semgrep.java.lang.security.audit.crypto.use-of-sha1": "WEAK_SIGNATURE_COMPARE",
    "java.lang.security.audit.crypto.use-of-sha1": "WEAK_SIGNATURE_COMPARE",
    "SEC-AUTHN-001": "AUTHORIZATION_BYPASS",
    "SEC-AUTHZ-002": "AUTHORIZATION_BYPASS",
    "SEC-CRYPTO-010": "WEAK_SIGNATURE_COMPARE",
    "SEC-DEBUG-011": "DEBUG_ENDPOINT_EXPOSURE",
    "JOLT_JAVA_CATCH_EXCEPTION": "BROAD_EXCEPTION",
    "CODE-EXC-003": "BROAD_EXCEPTION",
    "BE-ERR-003": "BROAD_EXCEPTION",
    "JOLT_JAVA_FIELD_AUTOWIRED": "SPRING_FIELD_INJECTION",
    "JOLT_JAVA_MISSING_TEST": "MISSING_TEST_COVERAGE",
    "TEST-COVER-001": "MISSING_TEST_COVERAGE",
    "jolt.test.skip-high-risk-path-tests": "MISSING_TEST_COVERAGE",
    "JOLT_DEP_HIGH_CVE": "DEPENDENCY_CVE",
    "DEP-CVE-001": "DEPENDENCY_CVE",
    "JOLT_DB_DROP_COLUMN": "DB_BREAKING_CHANGE",
    "jolt.db.drop-column": "DB_BREAKING_CHANGE",
    "DB-DDL-001": "DB_BREAKING_CHANGE",
    "JOLT_DB_NOT_NULL_NO_DEFAULT": "DB_NOT_NULL_NO_DEFAULT",
    "DB-NOTNULL-002": "DB_NOT_NULL_NO_DEFAULT",
    "JOLT_CONFIG_ACTUATOR_EXPOSE_ALL": "SPRING_ACTUATOR_EXPOSED",
    "SEC-CONFIG-007": "SPRING_ACTUATOR_EXPOSED",
    "PERF-QUERY-001": "UNBOUNDED_QUERY",
    "jolt.java.sql-query-without-limit": "UNBOUNDED_QUERY",
    "jolt.java.sql-leading-wildcard-like": "LIKE_LEADING_WILDCARD_INDEX_RISK",
    "PERF-MEM-004": "UNBOUNDED_RESULT_MEMORY",
    "CODE-NULL-001": "NULL_SAFETY",
    "jolt.java.loose-webhook-event-match": "STATE_MACHINE_INTEGRITY",
    "jolt.java.refund-allows-refunded-state": "STATE_MACHINE_INTEGRITY",
    "jolt.java.refund-reason-manual-override-bypass": "STATE_MACHINE_INTEGRITY",
    "jolt.java.force-capture-state-bypass": "STATE_MACHINE_INTEGRITY",
    "jolt.java.override-status-bypass": "STATE_MACHINE_INTEGRITY",
    "CODE-STATE-004": "STATE_MACHINE_INTEGRITY",
    "jolt.java.map-payload-string-valueof": "NULL_SAFETY",
    "jolt.java.refund-reason-startswith-null": "NULL_SAFETY",
    "jolt.java.payment-status-valueof-unvalidated": "NULL_SAFETY",
    "BE-IDEMP-004": "IDEMPOTENCY_GUARD",
    "jolt.java.domain-map-string-object": "DDD_WEAK_DOMAIN_MODEL",
    "jolt.java.reassign-merchant-ownership": "DDD_AGGREGATE_OWNERSHIP",
    "ALI-NAMING-001": "JAVA_NAMING",
    "ALI-NAMING-002": "JAVA_NAMING",
    "ALI-BIGDECIMAL-001": "BIGDECIMAL_PRECISION",
    "ALI-CONCURRENCY-001": "UNBOUNDED_EXECUTOR",
    "ALI-CONCURRENCY-002": "THREAD_UNSAFE_DATE_FORMAT",
    "ALI-CONCURRENCY-003": "THREADLOCAL_LEAK",
    "ALI-RETURN-001": "NULL_RETURN_COLLECTION",
    "ALI-EXC-002": "PRINT_STACK_TRACE",
    "ALI-LOG-001": "SYSTEM_OUT_LOGGING",
    "ALI-EQUALS-001": "EQUALS_HASHCODE_CONTRACT",
    "ALI-MYBATIS-001": "MYBATIS_SQL_INJECTION",
    "ALI-DB-001": "DB_MAP_RESULT_TYPE",
    "ALI-DB-002": "IBATIS_MEMORY_PAGINATION",
    "HW-PERF-001": "REQUEST_THREAD_BLOCKING",
    "HW-SEC-001": "INSECURE_RANDOM",
    "HW-LAYER-001": "LAYER_VIOLATION",
    "HW-TX-001": "TRANSACTION_PROXY_INVALID",
    "jolt.java.threadlocal-set-without-remove": "THREADLOCAL_LEAK",
    "jolt.java.threadlocal-read-in-new-thread": "THREADLOCAL_LEAK",
    "jolt.java.static-mutable-collection": "THREAD_UNSAFE_SHARED_STATE",
    "jolt.java.static-simpledateformat": "THREAD_UNSAFE_DATE_FORMAT",
    "jolt.java.bigdecimal-double-constructor": "BIGDECIMAL_PRECISION",
    "jolt.java.bigdecimal-floating-literal-constructor": "BIGDECIMAL_PRECISION",
    "jolt.java.localdatetime-now-idempotency-window": "IDEMPOTENCY_GUARD",
    "jolt.java.new-thread-in-spring-code": "UNBOUNDED_EXECUTOR",
    "jolt.java.return-internal-mutable-collection": "STATE_MACHINE_INTEGRITY",
    "jolt.java.transactional-self-invocation": "TRANSACTION_PROXY_INVALID",
    "jolt.java.jdbc-autocommit-not-restored": "DB_CONNECTION_STATE_LEAK",
}

CATEGORY_PRIMARY_RULE = {
    "SQL_INJECTION": "SEC-INJECT-003",
    "REDIS_DANGEROUS_COMMAND": "REDIS-CMD-003",
    "REDIS_MISSING_TTL": "REDIS-TTL-002",
    "DEPENDENCY_CVE": "DEP-CVE-001",
    "DEPENDENCY_SCOPE": "DEP-SCOPE-005",
    "DB_BREAKING_CHANGE": "DB-DDL-001",
    "DB_NOT_NULL_NO_DEFAULT": "DB-NOTNULL-002",
    "SPRING_VALIDATION": "BE-API-001",
    "ERROR_INFORMATION_LEAK": "SEC-SECRET-004:ERROR_RESPONSE",
    "BROAD_EXCEPTION": "CODE-EXC-003",
    "SECRET_LEAK": "SEC-SECRET-004",
    "SPRING_FIELD_INJECTION": "JOLT_JAVA_FIELD_AUTOWIRED",
    "MISSING_TEST_COVERAGE": "TEST-COVER-001",
    "SPRING_ACTUATOR_EXPOSED": "SEC-CONFIG-007",
    "DEBUG_ENDPOINT_EXPOSURE": "SEC-DEBUG-011",
    "WEAK_SIGNATURE_COMPARE": "SEC-CRYPTO-010",
    "UNTRUSTED_FORWARDED_HEADER": "SEC-RISK-006",
    "UNBOUNDED_QUERY": "PERF-QUERY-001",
    "UNBOUNDED_RESULT_MEMORY": "PERF-MEM-004",
    "DB_CONNECTION_STATE_LEAK": "CODE-RESOURCE-005",
    "NULL_SAFETY": "CODE-NULL-001",
    "IDEMPOTENCY_GUARD": "BE-IDEMP-004",
    "JAVA_NAMING": "ALI-NAMING-001",
    "BIGDECIMAL_PRECISION": "ALI-BIGDECIMAL-001",
    "UNBOUNDED_EXECUTOR": "ALI-CONCURRENCY-001",
    "THREAD_UNSAFE_DATE_FORMAT": "ALI-CONCURRENCY-002",
    "THREAD_UNSAFE_SHARED_STATE": "ALI-CONCURRENCY-002",
    "THREADLOCAL_LEAK": "ALI-CONCURRENCY-003",
    "NULL_RETURN_COLLECTION": "ALI-RETURN-001",
    "PRINT_STACK_TRACE": "ALI-EXC-002",
    "SYSTEM_OUT_LOGGING": "ALI-LOG-001",
    "EQUALS_HASHCODE_CONTRACT": "ALI-EQUALS-001",
    "MYBATIS_SQL_INJECTION": "ALI-MYBATIS-001",
    "DB_MAP_RESULT_TYPE": "ALI-DB-001",
    "IBATIS_MEMORY_PAGINATION": "ALI-DB-002",
    "REQUEST_THREAD_BLOCKING": "HW-PERF-001",
    "INSECURE_RANDOM": "HW-SEC-001",
    "LAYER_VIOLATION": "HW-LAYER-001",
    "TRANSACTION_PROXY_INVALID": "HW-TX-001",
    "DDD_WEAK_DOMAIN_MODEL": "DDD-VO-002",
    "AUTHORIZATION_BYPASS": "SEC-AUTHZ-002",
    "RISK_CONTROL_BYPASS": "SEC-RISK-006",
    "WEAK_WEBHOOK_TRUST": "SEC-WEBHOOK-008",
    "SSRF_CALLBACK": "SEC-SSRF-009",
    "CONFIG_SQL_LOGGING": "SEC-CONFIG-007",
    "STATE_MACHINE_INTEGRITY": "CODE-STATE-004",
    "LIKE_LEADING_WILDCARD_INDEX_RISK": "PERF-LIKE-002",
    "DDD_AGGREGATE_OWNERSHIP": "DDD-AGG-001",
}


def sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def canonical_rule_id(value: str | None) -> str:
    raw = str(value or "").strip()
    marker = ".prescan."
    if marker in raw:
        raw = raw.split(marker, 1)[1]
    return raw


def normalized_rule_category(rule_id: str | None, title: str | None = None) -> str:
    raw = canonical_rule_id(rule_id or title or "GENERAL")
    title_text = (title or "").lower()
    if raw == "SEC-CONFIG-007":
        if any(marker in title_text for marker in ["sha-1", "sha1", "signature", "签名", "弱摘要", "hmac"]):
            return "WEAK_SIGNATURE_COMPARE"
        if any(marker in title_text for marker in ["debug", "调试", "内部状态", "runtime state"]):
            return "DEBUG_ENDPOINT_EXPOSURE"
    if raw in RULE_CATEGORY_MAP:
        return RULE_CATEGORY_MAP[raw]
    lowered = raw.lower()
    combined = f"{lowered} {title_text}"
    if "jolt.java.spring.missing-valid-request-body" in combined:
        return "SPRING_VALIDATION"
    if "jolt.java.map-payload-string-valueof" in combined:
        return "NULL_SAFETY"
    if "jolt.java.jdbc.sql-concat" in combined or "jolt.java.jdbc.sql-string-concat-assignment" in combined:
        return "SQL_INJECTION"
    if "jolt.java.sql-query-without-limit" in combined:
        return "UNBOUNDED_QUERY"
    if "jolt.java.sql-leading-wildcard-like" in combined:
        return "LIKE_LEADING_WILDCARD_INDEX_RISK"
    if "jolt.java.domain-map-string-object" in combined:
        return "DDD_WEAK_DOMAIN_MODEL"
    if "jolt.java.redis.keys" in combined:
        return "REDIS_DANGEROUS_COMMAND"
    if "jolt.java.redis.set-without-ttl" in combined:
        return "REDIS_MISSING_TTL"
    if "jolt.db.drop-column" in combined:
        return "DB_BREAKING_CHANGE"
    if "jolt.config.hardcoded-password" in combined or "jolt.hardcoded-password" in combined:
        return "SECRET_LEAK"
    if "jolt.java.signature-string-equals" in combined:
        return "WEAK_SIGNATURE_COMPARE"
    if "jolt.java.spring-debug-endpoint-method" in combined:
        return "DEBUG_ENDPOINT_EXPOSURE"
    if "jolt.java.trust-x-forwarded-for" in combined:
        return "UNTRUSTED_FORWARDED_HEADER"
    if "use-of-sha1" in combined or "sha-1" in combined or "sha1" in combined:
        if any(marker in combined for marker in ["signature", "digest", "crypto", "message-digest", "签名", "摘要"]):
            return "WEAK_SIGNATURE_COMPARE"
    if "jolt.java.threadlocal-set-without-remove" in combined or "jolt.java.threadlocal-read-in-new-thread" in combined:
        return "THREADLOCAL_LEAK"
    if "jolt.java.static-mutable-collection" in combined:
        return "THREAD_UNSAFE_SHARED_STATE"
    if "jolt.java.static-simpledateformat" in combined:
        return "THREAD_UNSAFE_DATE_FORMAT"
    if "jolt.java.bigdecimal-double-constructor" in combined or "jolt.java.bigdecimal-floating-literal-constructor" in combined:
        return "BIGDECIMAL_PRECISION"
    if "jolt.java.localdatetime-now-idempotency-window" in combined:
        return "IDEMPOTENCY_GUARD"
    if "jolt.java.new-thread-in-spring-code" in combined:
        return "UNBOUNDED_EXECUTOR"
    if "jolt.java.return-internal-mutable-collection" in combined:
        return "STATE_MACHINE_INTEGRITY"
    if "jolt.java.transactional-self-invocation" in combined:
        return "TRANSACTION_PROXY_INVALID"
    if "jolt.java.jdbc-autocommit-not-restored" in combined:
        return "DB_CONNECTION_STATE_LEAK"
    if "sql" in combined and ("inject" in combined or "concat" in combined or "注入" in combined or "拼接" in combined):
        return "SQL_INJECTION"
    if ("redis" in combined or "keyspace" in combined) and "keys" in combined:
        return "REDIS_DANGEROUS_COMMAND"
    if ("ttl" in combined or "过期" in combined) and any(marker in combined for marker in ["redis", "cache", "缓存", "key "]):
        return "REDIS_MISSING_TTL"
    if (
        "cve" in combined
        or "vulnerab" in combined
        or "unsafe deserialization" in combined
        or "remote code execution" in combined
        or "fixed=" in combined
        or "known high-risk" in combined
    ):
        return "DEPENDENCY_CVE"
    if any(marker in combined for marker in ["sha-1", "sha1", "signature", "签名"]) and any(
        marker in combined for marker in ["equals", "常量时间", "constant-time", "弱摘要", "weak", "message digest"]
    ):
        return "WEAK_SIGNATURE_COMPARE"
    if "password" in combined or "secret" in combined or "token" in combined or "敏感" in combined or "密码" in combined or "凭据" in combined or "密钥" in combined:
        return "SECRET_LEAK"
    if "scope" in combined and ("junit" in combined or "test" in combined):
        return "DEPENDENCY_SCOPE"
    if "drop column" in combined or "drop table" in combined:
        return "DB_BREAKING_CHANGE"
    if "not null" in combined and ("default" in combined or "默认" in combined or "回填" in combined):
        return "DB_NOT_NULL_NO_DEFAULT"
    if "@valid" in combined or "bean validation" in combined or "入参" in combined:
        return "SPRING_VALIDATION"
    if "exception" in combined or "异常" in combined:
        if "响应" in combined or "客户端" in combined or "message" in combined:
            return "ERROR_INFORMATION_LEAK"
        return "BROAD_EXCEPTION"
    if "pagination" in combined or "limit" in combined or "分页" in combined or "unbounded query" in combined:
        return "UNBOUNDED_QUERY"
    if ("like" in combined or "模糊" in combined) and any(marker in combined for marker in ["leading wildcard", "前导通配", "前缀通配", "索引失效", "b+tree"]):
        return "LIKE_LEADING_WILDCARD_INDEX_RISK"
    if "resultset" in combined or "memory" in combined or "内存" in combined or "unbounded result" in combined:
        return "UNBOUNDED_RESULT_MEMORY"
    if "null" in combined or "空值" in combined or "nonnull" in combined:
        return "NULL_SAFETY"
    if "idempot" in combined or "幂等" in combined:
        return "IDEMPOTENCY_GUARD"
    if "bigdecimal" in combined and ("double" in combined or "float" in combined or "精度" in combined):
        return "BIGDECIMAL_PRECISION"
    if "executors" in combined or "线程池" in combined:
        return "UNBOUNDED_EXECUTOR"
    if "new thread" in combined or "raw thread" in combined or "直接创建线程" in combined:
        return "UNBOUNDED_EXECUTOR"
    if "simpledateformat" in combined:
        return "THREAD_UNSAFE_DATE_FORMAT"
    if "threadlocal" in combined:
        return "THREADLOCAL_LEAK"
    if "x-forwarded-for" in combined:
        return "UNTRUSTED_FORWARDED_HEADER"
    if "printstacktrace" in combined:
        return "PRINT_STACK_TRACE"
    if "system.out" in combined or "system.err" in combined:
        return "SYSTEM_OUT_LOGGING"
    if "equals" in combined and "hashcode" in combined:
        return "EQUALS_HASHCODE_CONTRACT"
    if "mybatis" in combined or "${}" in combined:
        return "MYBATIS_SQL_INJECTION"
    if "hashmap" in combined and ("db" in combined or "数据库" in combined or "result" in combined):
        return "DB_MAP_RESULT_TYPE"
    if "queryforlist" in combined:
        return "IBATIS_MEMORY_PAGINATION"
    if "map<string" in combined and ("domain" in combined or "aggregate" in combined or "value object" in combined or "value objects" in combined):
        return "DDD_WEAK_DOMAIN_MODEL"
    if "thread.sleep" in combined:
        return "REQUEST_THREAD_BLOCKING"
    if "securerandom" in combined or "java.util.random" in combined:
        return "INSECURE_RANDOM"
    if "repository" in combined and "controller" in combined:
        return "LAYER_VIOLATION"
    if "transactional" in combined and ("private" in combined or "final" in combined or "static" in combined):
        return "TRANSACTION_PROXY_INVALID"
    return re.sub(r"[^A-Z0-9_]+", "_", raw.upper()).strip("_") or "GENERAL"


def line_bucket(line: int | None, bucket_size: int = 5) -> int:
    if not line or line <= 0:
        return 0
    return ((int(line) - 1) // bucket_size) * bucket_size + 1


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()[:240]


def dedupe_hash_for_observation(
    *,
    rule_id: str | None,
    title: str | None,
    file_path: str,
    line_start: int | None,
    evidence: str | None,
) -> str:
    category = normalized_rule_category(rule_id, title)
    return sha1("|".join([category, file_path, str(line_bucket(line_start)), normalize_text(evidence)]))


def normalize_tool_finding(finding: dict[str, Any]) -> dict[str, Any]:
    item = dict(finding)
    covered = item.get("covered_rules") if isinstance(item.get("covered_rules"), list) else []
    title_text = " ".join(
        str(item.get(key) or "")
        for key in ["title", "problem_description", "recommendation", "evidence"]
    ).lower()
    file_path_text = str(item.get("file_path") or "").replace("\\", "/").lower()
    ddd_context = (
        "/domain/" in file_path_text
        or "domain model" in title_text
        or "aggregate" in title_text
        or "领域模型" in title_text
        or "聚合" in title_text
        or "值对象" in title_text
        or "value object" in title_text
    )
    if "redis" in title_text and "keys" in title_text and "REDIS-CMD-003" not in covered:
        covered = ["REDIS-CMD-003", *covered]
    if ("drop column" in title_text or "drop-column" in title_text) and "DB-DDL-001" not in covered:
        covered = ["DB-DDL-001", *covered]
    if "DDD-VO-002" in covered and not ddd_context:
        covered = [rule for rule in covered if rule != "DDD-VO-002"]
    if "map<string,object>" in title_text and ddd_context and "DDD-VO-002" not in covered:
        covered = ["DDD-VO-002", *covered]
    item["covered_rules"] = covered
    specific_covered = next(
        (
            str(rule)
            for rule in covered
            if rule and not str(rule).endswith("-001") and not str(rule).endswith("_MIGRATION-001")
        ),
        None,
    )
    rule_id = str(item.get("tool_rule_id") or item.get("rule_id") or specific_covered or item.get("title") or "")
    title = str(item.get("title") or rule_id or "tool finding")
    category = normalized_rule_category(rule_id, title)
    primary_rule = CATEGORY_PRIMARY_RULE.get(category)
    if primary_rule and primary_rule not in covered:
        covered = [*covered, primary_rule]
        item["covered_rules"] = covered
    item["normalized_rule_category"] = category
    item["tool_rule_id"] = rule_id or category
    if not item.get("covered_rules") and primary_rule:
        item["covered_rules"] = [primary_rule]
    item["dedupe_hash"] = dedupe_hash_for_observation(
        rule_id=rule_id,
        title=title,
        file_path=str(item.get("file_path") or ""),
        line_start=item.get("line_start"),
        evidence=str(item.get("evidence") or item.get("problem_description") or title),
    )
    return item


def dedupe_tool_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for finding in findings:
        item = normalize_tool_finding(finding)
        key = str(item["dedupe_hash"])
        previous = grouped.get(key)
        if not previous:
            item["tool_hit_count"] = 1
            item["tool_sources"] = [item.get("tool_name") or item.get("agent_id") or "unknown"]
            grouped[key] = item
            continue
        sources = set(previous.get("tool_sources") or [])
        sources.add(str(item.get("tool_name") or item.get("agent_id") or "unknown"))
        previous["tool_sources"] = sorted(sources)
        previous["tool_hit_count"] = int(previous.get("tool_hit_count") or 1) + 1
        previous["confidence"] = min(
            0.99,
            max(float(previous.get("confidence") or 0.5), float(item.get("confidence") or 0.5))
            + 0.1,
        )
        previous["evidence"] = str(previous.get("evidence") or item.get("evidence") or "")[:500]
    return list(grouped.values())
