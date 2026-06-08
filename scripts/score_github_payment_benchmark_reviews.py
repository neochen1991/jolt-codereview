from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from score_payment_benchmark_review import GROUND_TRUTH as PR1_GROUND_TRUTH


DEFAULT_DB = "data/jolt-codereview.sqlite"
DEFAULT_OUT = "docs/reports/2026-06-08-github-payment-3mr-quality-report.md"


PR1_MR = "mr_repo_3a83959a2dc948d6_3818935246"
PR2_MR = "mr_repo_3a83959a2dc948d6_3819251455"
PR3_MR = "mr_repo_3a83959a2dc948d6_3819353096"


PR2_GROUND_TRUTH = [
    {"id": "PR2-01", "title": "Export API Missing Auth And Ownership", "files": ["ExportController.java"], "patterns": [r"(auth|认证|授权|权限|归属|越权)", r"(export|导出|payments|支付数据)"]},
    {"id": "PR2-02", "title": "Export API Unbounded findAll", "files": ["ExportController.java"], "patterns": [r"(findAll|全表|unbounded|分页|limit|内存)", r"(export|导出|payment)"]},
    {"id": "PR2-03", "title": "Export merchantId Prefix/Null Risk", "files": ["ExportController.java"], "patterns": [r"(merchantId|getMerchantId|startsWith|前缀)", r"(null|NPE|空|归属|模糊)"]},
    {"id": "PR2-04", "title": "Reconciliation Import Missing Auth", "files": ["ReconciliationController.java"], "patterns": [r"(reconciliation|对账|import|导入)", r"(auth|认证|授权|权限|越权)"]},
    {"id": "PR2-05", "title": "Reconciliation rawCsv Null/Boundary", "files": ["ReconciliationService.java", "ReconcileRequest.java"], "patterns": [r"(rawCsv|CSV|split|对账)", r"(null|空|size|大小|边界|校验|非法)"]},
    {"id": "PR2-06", "title": "Reconciliation Amount Parse Exception", "files": ["ReconciliationService.java"], "patterns": [r"(BigDecimal|NumberFormatException|金额)", r"(catch|异常|未捕获|非法|校验)"]},
    {"id": "PR2-07", "title": "Reconciliation Raw CSV Audit Leak", "files": ["ReconciliationService.java"], "patterns": [r"(audit|审计|log|日志|write)", r"(rawCsv|raw|CSV|敏感|泄漏|泄露)"]},
    {"id": "PR2-08", "title": "Auto Settlement Full Scan/Long Transaction", "files": ["AutoSettlementService.java"], "patterns": [r"(findAll|全表|扫描|遍历|unbounded)", r"(transaction|事务|save|锁|长事务|定时)"]},
    {"id": "PR2-09", "title": "Auto Settlement Missing Idempotency/Concurrency Guard", "files": ["AutoSettlementService.java"], "patterns": [r"(自动结算|定时|scheduled|settlement)", r"(idempot|幂等|concurr|并发|锁|重复)"]},
    {"id": "PR2-10", "title": "Payment Static Cache Consistency/Memory Risk", "files": ["PaymentService.java"], "patterns": [r"(PAYMENT_CACHE|ConcurrentHashMap|cache|缓存)", r"(memory|内存|TTL|一致|stale|脏|持久层|无界)"]},
    {"id": "PR2-11", "title": "forceCapture Bypasses Payment State Machine", "files": ["PaymentService.java", "ConfirmPaymentRequest.java"], "patterns": [r"(forceCapture|settlementToken)", r"(bypass|绕过|重复|debit|扣款|状态|PAID|CREATED)"]},
    {"id": "PR2-12", "title": "PaymentAuditService Swallows IOException", "files": ["PaymentAuditService.java"], "patterns": [r"(IOException|ignored|catch|异常|审计)", r"(swallow|吞|静默|失败|无痕|silent)"]},
    {"id": "PR2-13", "title": "Refund Manual Override State Bypass", "files": ["RefundService.java"], "patterns": [r"(MANUAL_OVERRIDE|reason|退款)", r"(bypass|绕过|状态|PAID|资金|越权)"]},
    {"id": "PR2-14", "title": "Refund reason Null NPE", "files": ["RefundService.java"], "patterns": [r"(reason|request\.reason)", r"(null|NPE|空|startsWith)"]},
    {"id": "PR2-15", "title": "Webhook Dedupe Key Compatibility", "files": ["WebhookService.java"], "patterns": [r"(dedupeKey|eventId|providerTransactionId|去重键|幂等)", r"(兼容|migration|主键|重复|破坏|变更)"]},
    {"id": "PR2-16", "title": "Weak Webhook Signature Trust", "files": ["WebhookService.java"], "patterns": [r"(signature|签名)", r"(startsWith|prefix|前缀|test|weak|HMAC|伪造|不可信)"]},
    {"id": "PR2-17", "title": "Webhook Sensitive Logging", "files": ["WebhookService.java"], "patterns": [r"(audit|审计|log|日志|write)", r"(signature|rawPayload|payload|敏感|泄漏|泄露)"]},
]


PR3_GROUND_TRUTH = [
    {"id": "PR3-01", "title": "DDD Controller Missing Auth", "files": ["DddReviewController.java"], "patterns": [r"(/api/ddd|DddReviewController|敏感接口)", r"(auth|认证|授权|权限)"]},
    {"id": "PR3-02", "title": "Search merchantId IDOR", "files": ["DddReviewController.java"], "patterns": [r"(merchantId|searchPayments)", r"(归属|越权|IDOR|遍历|校验)"]},
    {"id": "PR3-03", "title": "Search Input Validation/Sort Whitelist", "files": ["DddReviewController.java", "PaymentSqlQueryRepository.java"], "patterns": [r"(merchantId|status|sort|排序)", r"(校验|白名单|入参|validation|RequestParam)"]},
    {"id": "PR3-04", "title": "forceTransition Arbitrary State/Merchant Change", "files": ["PaymentDddApplicationService.java", "DddReviewController.java"], "patterns": [r"(forceTransition|overrideStatus|reassignMerchant|强制状态)", r"(任意|状态|商户|归属|授权|绕过)"]},
    {"id": "PR3-05", "title": "RestTemplate No Timeout", "files": ["PaymentDddApplicationService.java"], "patterns": [r"(RestTemplate|HTTP|外部|callback)", r"(timeout|超时|重试|熔断|默认配置)"]},
    {"id": "PR3-06", "title": "Remote Call Inside Transaction", "files": ["PaymentDddApplicationService.java"], "patterns": [r"(Transactional|事务)", r"(RestTemplate|HTTP|外部调用|callback|远程)"]},
    {"id": "PR3-07", "title": "callbackUrl SSRF", "files": ["PaymentDddApplicationService.java", "DddReviewController.java"], "patterns": [r"(callbackUrl|callback|回调)", r"(SSRF|内网|allowlist|白名单|外连|校验)"]},
    {"id": "PR3-08", "title": "Missing Tests For DDD Application Service", "files": ["PaymentDddApplicationService.java"], "patterns": [r"(forceTransition|PaymentDddApplicationService)", r"(测试|test|覆盖|异常路径|状态流转)"]},
    {"id": "PR3-09", "title": "Lifecycle Policy Full Table Count/List", "files": ["PaymentLifecyclePolicy.java"], "patterns": [r"(riskRecords\.count|count\(\)|findByMerchantId|全部|全表|加载)", r"(性能|查询|N\+1|count|size|交易)"]},
    {"id": "PR3-10", "title": "Lifecycle Policy Hardcoded OR Logic", "files": ["PaymentLifecyclePolicy.java"], "patterns": [r"(5000\.00|globalRiskCount|merchantTransactions|裸数字|硬编码)", r"(\|\||或|OR|策略|风控|规则)"]},
    {"id": "PR3-11", "title": "overrideStatus valueOf Input Risk", "files": ["PaymentOrder.java"], "patterns": [r"(overrideStatus|valueOf|status)", r"(null|非法|IllegalArgumentException|NPE|校验)"]},
    {"id": "PR3-12", "title": "overrideStatus Bypasses State Machine", "files": ["PaymentOrder.java", "PaymentDddApplicationService.java"], "patterns": [r"(overrideStatus|状态机|状态流转)", r"(bypass|绕过|任意|终态|校验)"]},
    {"id": "PR3-13", "title": "reassignMerchant Breaks Ownership/Aggregate", "files": ["PaymentOrder.java", "PaymentDddApplicationService.java"], "patterns": [r"(reassignMerchant|merchantId|商户)", r"(归属|ownership|聚合|一致|任意|改写)"]},
    {"id": "PR3-14", "title": "Search SQL Injection", "files": ["PaymentSqlQueryRepository.java"], "patterns": [r"(SQL|sql|jdbc|query)", r"(拼接|注入|injection|PreparedStatement|参数绑定|sort)"]},
    {"id": "PR3-15", "title": "Snapshot Insert SQL Injection", "files": ["PaymentSqlQueryRepository.java"], "patterns": [r"(insertSnapshotRow|insert|payment_snapshots)", r"(拼接|注入|injection|PreparedStatement|参数绑定)"]},
    {"id": "PR3-16", "title": "Search Query Unbounded/No Limit", "files": ["PaymentSqlQueryRepository.java", "PaymentDddApplicationService.java"], "patterns": [r"(search|select \*|query|查询)", r"(limit|分页|unbounded|无上限|大结果|全表)"]},
    {"id": "PR3-17", "title": "LIKE Leading Wildcard Index Risk", "files": ["PaymentSqlQueryRepository.java"], "patterns": [r"(like|merchant_id|索引|index)", r"(%xxx%|前缀通配符|全表扫描|失效|B\+Tree)"]},
    {"id": "PR3-18", "title": "Repository Returns API DTO Layer Pollution", "files": ["PaymentSqlQueryRepository.java"], "patterns": [r"(PaymentResponse|DTO|api\.dto)", r"(repository|仓储|基础设施|层|污染|依赖)"]},
    {"id": "PR3-19", "title": "Schema Missing PK/NOT NULL/Index", "files": ["schema.sql"], "patterns": [r"(payment_snapshots|schema|表)", r"(主键|primary|NOT NULL|索引|index|null|约束)"]},
    {"id": "PR3-20", "title": "rebuildSnapshots findAll/N+1", "files": ["PaymentDddApplicationService.java"], "patterns": [r"(rebuildSnapshots|findAll|findById|快照)", r"(N\+1|全表|循环|分页|事务|查询)"]},
]


SUITES = {
    PR1_MR: {"name": "PR1 complex payment benchmark", "ground_truth": PR1_GROUND_TRUTH, "invalid_patterns": []},
    PR2_MR: {
        "name": "PR2 alternate payment benchmark",
        "ground_truth": PR2_GROUND_TRUTH,
        "invalid_patterns": [
            {"reason": "README generic-api-key false positive", "files": ["README.md"], "patterns": [r"(generic-api-key|明文密钥|配置或代码中包含明文密钥)"]},
            {"reason": "Redis finding without Redis evidence", "files": ["PaymentService.java"], "patterns": [r"Redis 缓存写入缺少 TTL|REDIS-TTL-002"]},
        ],
    },
    PR3_MR: {
        "name": "PR3 ddd sql benchmark",
        "ground_truth": PR3_GROUND_TRUTH,
        "invalid_patterns": [
            {"reason": "Finding is anchored to unchanged markRefunded context", "files": ["PaymentOrder.java"], "patterns": [r"markRefunded|already-refunded|已退款", r"line 112|:112|Refund logic allows"]},
        ],
    },
}


def load_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except json.JSONDecodeError:
        return fallback


def latest_run(conn: sqlite3.Connection, mr_id: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT rr.*
        FROM review_runs rr
        JOIN review_jobs rj ON rj.id = rr.review_job_id
        WHERE rj.merge_request_id = ?
        ORDER BY rr.started_at DESC
        LIMIT 1
        """,
        (mr_id,),
    ).fetchone()
    if not row:
        raise SystemExit(f"MR has no review run: {mr_id}")
    return row


def finding_text(row: sqlite3.Row) -> str:
    return "\n".join(
        str(row[key] or "")
        for key in [
            "title",
            "problem_description",
            "recommendation",
            "evidence",
            "suggested_code",
            "file_path",
            "covered_rules_json",
            "tool_provenance_json",
            "source_observations_json",
        ]
    )


def matches_spec(row: sqlite3.Row, spec: dict[str, Any]) -> bool:
    text = finding_text(row)
    file_path = str(row["file_path"] or "")
    if not any(file_name in file_path or file_name in text for file_name in spec["files"]):
        return False
    return all(re.search(pattern, text, re.IGNORECASE | re.MULTILINE) for pattern in spec["patterns"])


def summarize(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "agent_id": row["agent_id"],
        "severity": row["severity"],
        "confidence": row["confidence"],
        "file_path": row["file_path"],
        "line_start": row["line_start"],
        "title": row["title"],
        "covered_rules": load_json(row["covered_rules_json"], []),
        "tool_provenance": load_json(row["tool_provenance_json"], []),
    }


def severity_sort(row: sqlite3.Row) -> tuple[int, float]:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(str(row["severity"]), 0), float(row["confidence"] or 0)


def evaluate_suite(conn: sqlite3.Connection, mr_id: str, suite: dict[str, Any]) -> dict[str, Any]:
    run = latest_run(conn, mr_id)
    findings = conn.execute("SELECT * FROM review_findings WHERE review_run_id = ? ORDER BY severity DESC, confidence DESC", (run["id"],)).fetchall()
    matched_ids: set[str] = set()
    matched_finding_ids: set[str] = set()
    coverage: list[dict[str, Any]] = []
    for expected in suite["ground_truth"]:
        matches = [row for row in findings if matches_spec(row, expected)]
        matches.sort(key=severity_sort, reverse=True)
        if matches:
            matched_ids.add(str(expected["id"]))
            matched_finding_ids.add(str(matches[0]["id"]))
        coverage.append(
            {
                "id": expected["id"],
                "title": expected["title"],
                "matched": bool(matches),
                "matches": [summarize(row) for row in matches[:5]],
            }
        )

    invalid_rows = []
    for row in findings:
        if any(matches_spec(row, pattern) for pattern in suite.get("invalid_patterns", [])):
            invalid_rows.append(row)

    valid_duplicate_rows = []
    for row in findings:
        if str(row["id"]) in matched_finding_ids:
            continue
        if any(matches_spec(row, expected) for expected in suite["ground_truth"]):
            valid_duplicate_rows.append(row)

    expected_count = len(suite["ground_truth"])
    recall = len(matched_ids) / expected_count if expected_count else 0.0
    false_positive_rate = len(invalid_rows) / len(findings) if findings else 0.0
    budget = load_json(run["budget_used_json"], {})
    return {
        "mr_id": mr_id,
        "name": suite["name"],
        "run_id": run["id"],
        "status": run["status"],
        "expected_count": expected_count,
        "finding_count": len(findings),
        "matched_count": len(matched_ids),
        "missing_count": expected_count - len(matched_ids),
        "invalid_false_positive_count": len(invalid_rows),
        "valid_duplicate_count": len(valid_duplicate_rows),
        "recall": round(recall, 4),
        "false_positive_rate": round(false_positive_rate, 4),
        "meets_target": recall >= 0.9 and false_positive_rate <= 0.1,
        "budget": budget,
        "coverage": coverage,
        "invalid_false_positives": [summarize(row) for row in invalid_rows],
        "valid_duplicates": [summarize(row) for row in valid_duplicate_rows],
    }


def render_markdown(reports: list[dict[str, Any]]) -> str:
    total_expected = sum(item["expected_count"] for item in reports)
    total_matched = sum(item["matched_count"] for item in reports)
    total_findings = sum(item["finding_count"] for item in reports)
    total_invalid = sum(item["invalid_false_positive_count"] for item in reports)
    overall_recall = total_matched / total_expected if total_expected else 0
    overall_fp = total_invalid / total_findings if total_findings else 0
    lines = [
        "# GitHub Payment Benchmark 3MR Quality Report",
        "",
        f"- Overall Recall: {overall_recall:.4f}",
        f"- Overall Invalid False Positive Rate: {overall_fp:.4f}",
        f"- Meets Target: {'yes' if overall_recall >= 0.9 and overall_fp <= 0.1 and all(item['meets_target'] for item in reports) else 'no'}",
        "",
        "| MR | Run | Expected | Matched | Missing | Findings | Invalid FP | Recall | FP Rate | Target |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for report in reports:
        lines.append(
            f"| {report['name']} | `{report['run_id']}` | {report['expected_count']} | {report['matched_count']} | "
            f"{report['missing_count']} | {report['finding_count']} | {report['invalid_false_positive_count']} | "
            f"{report['recall']:.4f} | {report['false_positive_rate']:.4f} | {'yes' if report['meets_target'] else 'no'} |"
        )
    for report in reports:
        lines.extend(["", f"## {report['name']}", "", "| ID | Expected Issue | Status | Best Match |", "| --- | --- | --- | --- |"])
        for item in report["coverage"]:
            best = item["matches"][0] if item["matches"] else None
            match = f"{best['title']} ({best['file_path']}:{best['line_start'] or '-'})" if best else "-"
            lines.append(f"| {item['id']} | {item['title']} | {'matched' if item['matched'] else 'missing'} | {match} |")
        lines.extend(["", "Invalid false positives:"])
        if report["invalid_false_positives"]:
            for fp in report["invalid_false_positives"]:
                lines.append(f"- {fp['title']} ({fp['agent_id']}, {fp['file_path']}:{fp['line_start'] or '-'})")
        else:
            lines.append("- None")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    reports = [evaluate_suite(conn, mr_id, suite) for mr_id, suite in SUITES.items()]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(reports), "utf-8")
    payload = {
        "reports": reports,
        "overall": {
            "recall": round(sum(item["matched_count"] for item in reports) / sum(item["expected_count"] for item in reports), 4),
            "false_positive_rate": round(sum(item["invalid_false_positive_count"] for item in reports) / sum(item["finding_count"] for item in reports), 4),
        },
    }
    if args.json_out:
        json_out = Path(args.json_out)
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
