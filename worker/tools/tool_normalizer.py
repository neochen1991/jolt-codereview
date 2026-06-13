from __future__ import annotations

import hashlib
import re
from typing import Any

DDD_RULE_IDS = {
    "DDD-CTX-001", "DDD-CTX-002", "DDD-CTX-003", "DDD-CTX-004", "DDD-CTX-005",
    "DDD-AGG-001", "DDD-AGG-002", "DDD-AGG-003", "DDD-AGG-004", "DDD-AGG-005", "DDD-AGG-006", "DDD-AGG-007", "DDD-AGG-008", "DDD-AGG-009", "DDD-AGG-010",
    "DDD-ENT-001", "DDD-ENT-002",
    "DDD-VO-001", "DDD-VO-002", "DDD-VO-003", "DDD-VO-004", "DDD-VO-005", "DDD-VO-006", "DDD-VO-007",
    "DDD-APP-001", "DDD-APP-002", "DDD-APP-003", "DDD-APP-004", "DDD-APP-005",
    "DDD-DOM-SVC-001", "DDD-DOM-SVC-002", "DDD-POLICY-001",
    "DDD-REPO-001", "DDD-REPO-002", "DDD-REPO-003", "DDD-REPO-004",
    "DDD-INFRA-001", "DDD-INFRA-002", "DDD-INFRA-003",
    "DDD-EVENT-001", "DDD-EVENT-002", "DDD-EVENT-003", "DDD-EVENT-004", "DDD-EVENT-005", "DDD-EVENT-006",
    "DDD-LAYER-001", "DDD-LAYER-002", "DDD-LAYER-003", "DDD-LAYER-004", "DDD-LAYER-005",
    "DDD-RULE-001", "DDD-RULE-002", "DDD-RULE-003", "DDD-RULE-004", "DDD-RULE-005", "DDD-RULE-006",
    "DDD-CQRS-001", "DDD-CQRS-002", "DDD-CQRS-003", "DDD-CQRS-004",
    "DDD-EVO-001", "DDD-EVO-002", "DDD-EVO-003", "DDD-EVO-004",
    "DDD-TENANT-001", "DDD-TENANT-002", "DDD-TENANT-003",
}


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
    "config.static-rules.semgrep.java.lang.security.audit.crypto.use-of-sha1": "WEAK_SIGNATURE_ALGORITHM",
    "java.lang.security.audit.crypto.use-of-sha1": "WEAK_SIGNATURE_ALGORITHM",
    "SEC-AUTHN-001": "AUTHORIZATION_BYPASS",
    "SEC-AUTHZ-002": "AUTHORIZATION_BYPASS",
    "SEC-CRYPTO-010": "WEAK_SIGNATURE_COMPARE",
    "SEC-CRYPTO-011": "WEAK_SIGNATURE_ALGORITHM",
    "SEC-DEBUG-011": "DEBUG_ENDPOINT_EXPOSURE",
    "JOLT_JAVA_CATCH_EXCEPTION": "BROAD_EXCEPTION",
    "CODE-EXC-003": "BROAD_EXCEPTION",
    "BE-ERR-003": "BROAD_EXCEPTION",
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
    "config.static-rules.semgrep.java.spring.security.audit.spel-injection": "SPEL_INJECTION",
    "spring.security.audit.spel-injection": "SPEL_INJECTION",
    "spel-injection": "SPEL_INJECTION",
    "jolt.java.spel-standard-evaluation-context": "SPEL_INJECTION",
    "jolt.java.spel-executable-default-expression": "SPEL_INJECTION",
    "config.static-rules.semgrep.java.jolt.jolt.java.spel-executable-default-expression": "SPEL_INJECTION",
    "config.static-rules.semgrep.java.lang.security.audit.unsafe-reflection": "UNSAFE_REFLECTION",
    "lang.security.audit.unsafe-reflection": "UNSAFE_REFLECTION",
    "unsafe-reflection": "UNSAFE_REFLECTION",
    "jolt.java.failure-default-allow": "FAILURE_DEFAULT_ALLOW",
    "jolt.java.fixed-active-cache-key": "CACHE_KEY_COLLISION",
    "jolt.java.bigdecimal-equals-money": "BIGDECIMAL_PRECISION",
    "config.static-rules.semgrep.java.jolt.jolt.java.bigdecimal-getter-equals-money": "BIGDECIMAL_PRECISION",
    "jolt.java.bigdecimal-getter-equals-money": "BIGDECIMAL_PRECISION",
    "config.static-rules.semgrep.java.jolt.jolt.java.sensitive-request-param-secret": "SECRET_LEAK",
    "jolt.java.sensitive-request-param-secret": "SECRET_LEAK",
    "jolt.java.random-in-risk-or-security-decision": "INSECURE_RANDOM",
    "config.static-rules.semgrep.java.jolt.jolt.java.secure-random-fixed-seed": "INSECURE_RANDOM",
    "jolt.java.secure-random-fixed-seed": "INSECURE_RANDOM",
    "config.static-rules.semgrep.java.jolt.jolt.java.preview-findall-cross-tenant-leak": "AUTHORIZATION_BYPASS",
    "jolt.java.preview-findall-cross-tenant-leak": "AUTHORIZATION_BYPASS",
    "config.static-rules.semgrep.java.jolt.jolt.java.policy-priority-stored-not-selected": "DDD_POLICY_001",
    "jolt.java.policy-priority-stored-not-selected": "DDD_POLICY_001",
    "config.static-rules.semgrep.java.lang.security.audit.object-deserialization": "UNSAFE_DESERIALIZATION",
    "lang.security.audit.object-deserialization": "UNSAFE_DESERIALIZATION",
    "object-deserialization": "UNSAFE_DESERIALIZATION",
    "jolt.java.objectinputstream-readobject": "UNSAFE_DESERIALIZATION",
    "jolt.java.zip-entry-write-without-normalize-guard": "ZIP_SLIP",
    "jolt.java.zip-processing-without-size-limit": "ARCHIVE_BOMB_RISK",
    "config.static-rules.semgrep.java.lang.security.java-pattern-from-string-parameter": "REGEX_DOS",
    "lang.security.java-pattern-from-string-parameter": "REGEX_DOS",
    "java-pattern-from-string-parameter": "REGEX_DOS",
    "jolt.java.csv-response-without-escaping": "CSV_OUTPUT_INJECTION",
    "jolt.java.content-disposition-unsanitized-filename": "UNSAFE_FILE_RESPONSE",
    "jolt.java.zip-parent-mkdirs-unchecked": "ZIP_ENTRY_MKDIRS_IGNORED",
    "jolt.java.zipinputstream-without-try-resources": "ZIP_STREAM_RESOURCE_LEAK",
    "jolt.java.regex-pattern-compile-user-input": "REGEX_DOS",
    "jolt.java.default-charset-csv-io": "DEFAULT_CHARSET_IO",
    "jolt.java.localdatetime-now-export-audit": "AUDIT_TIME_ZONE",
    "jolt.java.predictable-temp-file": "PREDICTABLE_TEMP_FILE",
    "jolt.java.serializable-command-without-filter": "UNSAFE_DESERIALIZATION",
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
    "MISSING_TEST_COVERAGE": "TEST-COVER-001",
    "SPRING_ACTUATOR_EXPOSED": "SEC-CONFIG-007",
    "DEBUG_ENDPOINT_EXPOSURE": "SEC-DEBUG-011",
    "WEAK_SIGNATURE_COMPARE": "SEC-CRYPTO-010",
    "WEAK_SIGNATURE_ALGORITHM": "SEC-CRYPTO-011",
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
    "SPEL_INJECTION": "SEC-INJECT-003",
    "UNSAFE_REFLECTION": "SEC-INJECT-003",
    "FAILURE_DEFAULT_ALLOW": "SEC-RISK-006",
    "CACHE_KEY_COLLISION": "CODE-STATE-004",
    "INSECURE_RANDOM": "HW-SEC-001",
    "UNSAFE_DESERIALIZATION": "SEC-INJECT-003",
    "ZIP_SLIP": "SEC-INJECT-003",
    "ARCHIVE_BOMB_RISK": "PERF-MEM-004",
    "REGEX_DOS": "SEC-RISK-006",
    "CSV_OUTPUT_INJECTION": "SEC-INJECT-003",
    "UNSAFE_FILE_RESPONSE": "SEC-INJECT-003",
    "ZIP_ENTRY_MKDIRS_IGNORED": "CODE-RESOURCE-005",
    "ZIP_STREAM_RESOURCE_LEAK": "CODE-RESOURCE-005",
    "DEFAULT_CHARSET_IO": "CODE-STATE-004",
    "AUDIT_TIME_ZONE": "CODE-STATE-004",
    "PREDICTABLE_TEMP_FILE": "SEC-RISK-006",
}

for _ddd_rule_id in DDD_RULE_IDS:
    RULE_CATEGORY_MAP.setdefault(_ddd_rule_id, _ddd_rule_id.replace("-", "_"))
    CATEGORY_PRIMARY_RULE.setdefault(_ddd_rule_id.replace("-", "_"), _ddd_rule_id)


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
    if raw.upper().startswith("DDD-"):
        return raw.upper().replace("-", "_")
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
            return "WEAK_SIGNATURE_ALGORITHM"
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
    if (
        "spel-injection" in combined
        or "jolt.java.spel-standard-evaluation-context" in combined
        or "jolt.java.spel-executable-default-expression" in combined
        or ("spel" in combined and "standardevaluationcontext" in combined)
    ):
        return "SPEL_INJECTION"
    if "unsafe-reflection" in combined or ("class.forname" in combined and ("request" in combined or "user" in combined or "external" in combined or "外部" in combined)):
        return "UNSAFE_REFLECTION"
    if "jolt.java.failure-default-allow" in combined or ("default" in combined and ("allow" in combined or "pass" in combined)):
        return "FAILURE_DEFAULT_ALLOW"
    if "jolt.java.fixed-active-cache-key" in combined:
        return "CACHE_KEY_COLLISION"
    if "jolt.java.bigdecimal-equals-money" in combined:
        return "BIGDECIMAL_PRECISION"
    if "jolt.java.random-in-risk-or-security-decision" in combined or "jolt.java.secure-random-fixed-seed" in combined:
        return "INSECURE_RANDOM"
    if "jolt.java.preview-findall-cross-tenant-leak" in combined:
        return "AUTHORIZATION_BYPASS"
    if "jolt.java.policy-priority-stored-not-selected" in combined:
        return "DDD_POLICY_001"
    if "object-deserialization" in combined or "jolt.java.objectinputstream-readobject" in combined or "objectinputstream" in combined:
        return "UNSAFE_DESERIALIZATION"
    if "jolt.java.zip-entry-write-without-normalize-guard" in combined or "zip slip" in combined or "zipslip" in combined:
        return "ZIP_SLIP"
    if "jolt.java.zip-processing-without-size-limit" in combined or "zip bomb" in combined:
        return "ARCHIVE_BOMB_RISK"
    if "java-pattern-from-string-parameter" in combined or "jolt.java.regex-pattern-compile-user-input" in combined or "redos" in combined:
        return "REGEX_DOS"
    if "jolt.java.csv-response-without-escaping" in combined or "csv formula" in combined:
        return "CSV_OUTPUT_INJECTION"
    if "jolt.java.content-disposition-unsanitized-filename" in combined:
        return "UNSAFE_FILE_RESPONSE"
    if "jolt.java.zip-parent-mkdirs-unchecked" in combined or ("mkdirs" in combined and "return" in combined):
        return "ZIP_ENTRY_MKDIRS_IGNORED"
    if "jolt.java.zipinputstream-without-try-resources" in combined or ("zipinputstream" in combined and ("close" in combined or "try-with-resources" in combined)):
        return "ZIP_STREAM_RESOURCE_LEAK"
    if "jolt.java.default-charset-csv-io" in combined or ("default charset" in combined and ("csv" in combined or "file" in combined)):
        return "DEFAULT_CHARSET_IO"
    if "jolt.java.localdatetime-now-export-audit" in combined or ("localdatetime.now" in combined and ("audit" in combined or "export" in combined or "settlement" in combined)):
        return "AUDIT_TIME_ZONE"
    if "jolt.java.predictable-temp-file" in combined or ("java.io.tmpdir" in combined and ("predictable" in combined or "last-" in combined)):
        return "PREDICTABLE_TEMP_FILE"
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
        if "sha-1" in combined or "sha1" in combined or "弱摘要" in combined:
            return "WEAK_SIGNATURE_ALGORITHM"
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
        or "/application/" in file_path_text
        or "/service/" in file_path_text
        or "/repository/" in file_path_text
        or "/event/" in file_path_text
        or "domain model" in title_text
        or "aggregate" in title_text
        or "application service" in title_text
        or "repository" in title_text
        or "domain event" in title_text
        or "bounded context" in title_text
        or "tenant" in title_text
        or "merchant" in title_text
        or "领域模型" in title_text
        or "聚合" in title_text
        or "值对象" in title_text
        or "应用服务" in title_text
        or "仓储" in title_text
        or "领域事件" in title_text
        or "限界上下文" in title_text
        or "租户" in title_text
        or "商户" in title_text
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
