from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

from orchestration.nodes.judge_findings import _root_cause_signature


def finding(title: str, *, file_path: str = "src/main/java/com/acme/payment/service/PaymentService.java") -> dict:
    return {
        "title": title,
        "problem_description": title,
        "recommendation": "修复该问题。",
        "evidence": title,
        "file_path": file_path,
        "covered_rules": [],
    }


def test_root_cause_signature_covers_rare_business_and_code_patterns() -> None:
    cases = [
        (
            finding("SQL 注入：使用字符串拼接构造 SQL 查询，用户输入直接进入 where 条件"),
            "SQL_STRING_CONCAT_QUERY",
        ),
        (
            finding("Redis KEYS 命令扫描线上 keyspace，可能阻塞主线程"),
            "REDIS_KEYS_COMMAND",
        ),
        (
            finding("Redis 缓存写入 without TTL，热点数据没有设置过期时间"),
            "REDIS_MISSING_TTL",
        ),
        (
            finding("动态堆体聚合用 Map<String,Object> 表示 domain 状态，缺少值对象约束"),
            "DOMAIN_WEAK_MAP_STATE",
        ),
        (
            finding("批量 @RequestBody List<Adjustment> 无上限，长事务和内存压力不可控"),
            "UNBOUNDED_REQUEST_BODY",
        ),
        (
            finding("catch Exception 后吞异常并伪造成功，writeBalanceAdjustment 写入失败会被忽略"),
            "SWALLOWED_EXCEPTION_WRITE",
        ),
        (
            finding("JDBC Connection/Statement 资源未关闭，loadRecentAuditPaymentIds 读取路径泄漏连接"),
            "JDBC_RESOURCE_LIFECYCLE_LOAD",
        ),
        (
            finding("debug endpoint 暴露内部状态，@GetMapping 可直接读取调试信息"),
            "DEBUG_ENDPOINT_EXPOSURE",
        ),
        (
            finding("ThreadLocal CURRENT_TENANT set 后没有 remove，线程复用时会泄漏租户上下文"),
            "THREADLOCAL_LIFECYCLE",
        ),
        (
            finding("signature.equals 用于比较 webhook 签名，非 constant-time 可能产生 timing 泄露"),
            "WEAK_SIGNATURE_COMPARE",
        ),
        (
            finding("manual_override 绕过退款状态机，reason 为空仍允许状态切换", file_path="src/main/java/com/acme/payment/service/RefundService.java"),
            "REFUND_REASON_STATE_BYPASS",
        ),
        (
            finding("dedupeKey 使用 eventId:providerTransactionId，WebhookService 对历史事件兼容性不足", file_path="src/main/java/com/acme/payment/service/WebhookService.java"),
            "WEBHOOK_DEDUPE_KEY_COMPATIBILITY",
        ),
    ]
    for item, expected in cases:
        assert _root_cause_signature(item) == expected, (item, expected, _root_cause_signature(item))


if __name__ == "__main__":
    test_root_cause_signature_covers_rare_business_and_code_patterns()
