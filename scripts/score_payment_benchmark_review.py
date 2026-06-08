from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_MR_ID = "mr_repo_3a83959a2dc948d6_3818935246"
DEFAULT_DB = "data/jolt-codereview.sqlite"
DEFAULT_OUT = "docs/reports/2026-06-07-payment-benchmark-real-mr-quality-report.md"


GROUND_TRUTH = [
    {
        "id": 1,
        "title": "Unauthenticated Admin Balance Adjustment",
        "files": ["AccountController.java", "AccountService.java", "AdminBalanceAdjustmentRequest.java"],
        "patterns": [r"admin", r"adjust", r"(auth|认证|授权|权限|unauthori)"],
    },
    {
        "id": 2,
        "title": "Unsafe Negative and Arbitrary Balance Changes",
        "files": ["AccountService.java", "AdminBalanceAdjustmentRequest.java"],
        "patterns": [r"(adjustBalance|调账|balance)", r"(negative|负|amount|金额|currency|operator|reason|limit|上限|下限|任意|arbitrary)"],
    },
    {
        "id": 3,
        "title": "Sensitive Card Data Accepted and Stored",
        "files": ["CreatePaymentRequest.java", "PaymentOrder.java"],
        "patterns": [r"(cardNumber|cvv|card|凭据|敏感|PCI)", r"(PaymentOrder|CreatePaymentRequest|store|persist|database|存储|持久|token)"],
    },
    {
        "id": 4,
        "title": "Sensitive Card Data Returned in API Responses",
        "files": ["PaymentResponse.java"],
        "patterns": [r"(PaymentResponse|response|响应|返回|API)", r"(cardNumber|cvv|card|凭据|敏感|泄露)"],
    },
    {
        "id": 5,
        "title": "Sensitive Data Logged",
        "files": ["PaymentService.java"],
        "patterns": [r"(log\.|日志|logging|记录)", r"(cardNumber|cvv|callbackUrl|signature|rawPayload|敏感|凭据|泄露)"],
    },
    {
        "id": 6,
        "title": "Risk-Control Bypass Flag",
        "files": ["ConfirmPaymentRequest.java", "PaymentService.java"],
        "patterns": [r"skipRiskCheck", r"(risk|风控|bypass|跳过|绕过)"],
    },
    {
        "id": 7,
        "title": "Localhost IP Risk Bypass",
        "files": ["PaymentService.java"],
        "patterns": [r"(127\.0\.0\.1|clientIp|localhost)", r"(risk|风控|bypass|跳过|绕过|spoof)"],
    },
    {
        "id": 8,
        "title": "Money Precision Loss",
        "files": ["MoneyNormalizer.java", "PaymentService.java", "RefundService.java"],
        "patterns": [r"(BigDecimal|MoneyNormalizer|金额|money)", r"(doubleValue|double|precision|精度|round|舍入)"],
    },
    {
        "id": 9,
        "title": "Refund Allowed After Already Refunded",
        "files": ["RefundService.java"],
        "patterns": [r"(REFUNDED|refunded|退款)", r"(again|重复|再次|multiple|多次|idempotency|状态)"],
    },
    {
        "id": 10,
        "title": "Refund Amount Not Compared to Paid Amount or Prior Refunds",
        "files": ["RefundService.java"],
        "patterns": [r"(refund|退款)", r"(amount|金额|paid|original|cumulative|prior|exceed|超过|累计|原支付)"],
    },
    {
        "id": 11,
        "title": "Weak Webhook Signature Trust",
        "files": ["WebhookService.java"],
        "patterns": [r"(signature|签名)", r"(contains|startsWith|test|weak|HMAC|cryptographic|伪造|校验)"],
    },
    {
        "id": 12,
        "title": "Loose Webhook Event Matching",
        "files": ["WebhookService.java"],
        "patterns": [r"(eventType|event type|事件)", r"(contains|PAYMENT_SUCCEEDED|exact|精确|malformed|恶意)"],
    },
    {
        "id": 13,
        "title": "Untrusted Callback URL Invocation",
        "files": ["NotificationService.java", "PaymentService.java", "PaymentOrder.java"],
        "patterns": [r"(callbackUrl|callback|回调|RestTemplate|postForEntity)", r"(SSRF|untrusted|allowlist|内网|外发|exfiltrat|校验|timeout|敏感)"],
    },
    {
        "id": 14,
        "title": "Debug Endpoints Expose Internal Data",
        "files": ["BenchmarkDebugController.java", "README.md"],
        "patterns": [r"(debug|/api/debug|BenchmarkDebugController)", r"(auth|认证|授权|internal|raw|entity|暴露|枚举|PaymentOrder|RefundOrder|WebhookEvent)"],
    },
    {
        "id": 15,
        "title": "Stack Trace Leakage",
        "files": ["GlobalExceptionHandler.java", "application.yml"],
        "patterns": [r"(stacktrace|stack trace|printStackTrace|StringWriter|include-stacktrace|堆栈)", r"(response|client|ErrorResponse|泄露|返回)"],
    },
    {
        "id": 16,
        "title": "SQL Logging Enabled in Application Config",
        "files": ["application.yml"],
        "patterns": [r"(show-sql|SQL logging|sql.*日志|SQL.*泄露)", r"(true|enabled|application\.yml|配置)"],
    },
    {
        "id": 17,
        "title": "Test Configuration Masks Missing Coverage",
        "files": ["application-test.yml"],
        "patterns": [r"(skip-external-callback-tests|skip.*callback|测试配置|missing coverage|缺少.*测试)", r"(callback|debug|admin|auth|coverage|覆盖)"],
    },
]


def load_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except json.JSONDecodeError:
        return fallback


def finding_text(row: sqlite3.Row) -> str:
    parts = [
        row["title"],
        row["problem_description"],
        row["recommendation"],
        row["evidence"],
        row["suggested_code"],
        row["file_path"],
        row["covered_rules_json"],
        row["tool_provenance_json"],
        row["source_observations_json"],
    ]
    return "\n".join(str(part or "") for part in parts)


def matches_expected(row: sqlite3.Row, expected: dict[str, Any]) -> bool:
    text = finding_text(row)
    file_path = str(row["file_path"] or "")
    has_file = any(file_name in file_path or file_name in text for file_name in expected["files"])
    if not has_file:
        return False
    return all(re.search(pattern, text, re.IGNORECASE | re.MULTILINE) for pattern in expected["patterns"])


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


def severity_sort(row: sqlite3.Row) -> tuple[int, float]:
    rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(str(row["severity"]), 0)
    return rank, float(row["confidence"] or 0)


def evaluate(conn: sqlite3.Connection, mr_id: str) -> dict[str, Any]:
    conn.row_factory = sqlite3.Row
    run = latest_run(conn, mr_id)
    findings = conn.execute(
        """
        SELECT *
        FROM review_findings
        WHERE review_run_id = ?
        ORDER BY selected DESC, severity DESC, confidence DESC, created_at
        """,
        (run["id"],),
    ).fetchall()
    matched_by_issue: dict[int, list[dict[str, Any]]] = {}
    matched_finding_ids: set[str] = set()
    for expected in GROUND_TRUTH:
        matches = [row for row in findings if matches_expected(row, expected)]
        matches.sort(key=severity_sort, reverse=True)
        if matches:
            matched_by_issue[expected["id"]] = [summarize_finding(row) for row in matches[:5]]
            matched_finding_ids.add(str(matches[0]["id"]))
        else:
            matched_by_issue[expected["id"]] = []
    false_positive_rows = [row for row in findings if not any(matches_expected(row, expected) for expected in GROUND_TRUTH)]
    duplicate_rows = [
        row
        for row in findings
        if any(matches_expected(row, expected) for expected in GROUND_TRUTH)
        and str(row["id"]) not in matched_finding_ids
    ]
    matched_count = sum(1 for rows in matched_by_issue.values() if rows)
    recall = matched_count / len(GROUND_TRUTH)
    fp_rate = len(false_positive_rows) / len(findings) if findings else 0.0
    budget = load_json(run["budget_used_json"], {})
    coverage = load_json(run["coverage_json"], {})
    return {
        "mr_id": mr_id,
        "run_id": run["id"],
        "run_status": run["status"],
        "report_summary": run["report_summary"],
        "expected_count": len(GROUND_TRUTH),
        "finding_count": len(findings),
        "matched_count": matched_count,
        "missing_count": len(GROUND_TRUTH) - matched_count,
        "false_positive_count": len(false_positive_rows),
        "duplicate_valid_finding_count": len(duplicate_rows),
        "recall": round(recall, 4),
        "false_positive_rate": round(fp_rate, 4),
        "meets_target": recall >= 0.9 and fp_rate <= 0.1,
        "budget": budget,
        "coverage": coverage,
        "issues": [
            {
                "id": expected["id"],
                "title": expected["title"],
                "matched": bool(matched_by_issue[expected["id"]]),
                "matches": matched_by_issue[expected["id"]],
            }
            for expected in GROUND_TRUTH
        ],
        "false_positives": [summarize_finding(row) for row in false_positive_rows],
        "duplicates": [summarize_finding(row) for row in duplicate_rows],
    }


def summarize_finding(row: sqlite3.Row) -> dict[str, Any]:
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


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Payment Benchmark Real MR Quality Report",
        "",
        f"- MR: `{report['mr_id']}`",
        f"- Run: `{report['run_id']}`",
        f"- Status: `{report['run_status']}`",
        f"- Summary: {report.get('report_summary') or '-'}",
        f"- Expected Issues: {report['expected_count']}",
        f"- Final Findings: {report['finding_count']}",
        f"- Matched Issues: {report['matched_count']}",
        f"- Missing Issues: {report['missing_count']}",
        f"- False Positive Findings: {report['false_positive_count']}",
        f"- Duplicate Valid Findings: {report['duplicate_valid_finding_count']}",
        f"- Recall: {report['recall']:.4f}",
        f"- False Positive Rate: {report['false_positive_rate']:.4f}",
        f"- Meets Target: {'yes' if report['meets_target'] else 'no'}",
        f"- LLM Calls: {report['budget'].get('llm_calls', 0)}",
        f"- Tool Calls: {report['budget'].get('tool_calls', 0)}",
        f"- Truncated Reason: {report['budget'].get('truncated_reason') or 'none'}",
        "",
        "## Issue Coverage",
        "",
        "| # | Expected Issue | Status | Best Match |",
        "| ---: | --- | --- | --- |",
    ]
    for issue in report["issues"]:
        if issue["matches"]:
            best = issue["matches"][0]
            match = f"{best['title']} ({best['file_path']}:{best['line_start'] or '-'})"
        else:
            match = "-"
        lines.append(f"| {issue['id']} | {issue['title']} | {'matched' if issue['matched'] else 'missing'} | {match} |")

    lines.extend(["", "## False Positive Findings", ""])
    if report["false_positives"]:
        for item in report["false_positives"]:
            lines.append(f"- {item['title']} ({item['agent_id']}, {item['file_path']}:{item['line_start'] or '-'})")
    else:
        lines.append("None.")

    lines.extend(["", "## Duplicate Valid Findings", ""])
    if report["duplicates"]:
        for item in report["duplicates"]:
            lines.append(f"- {item['title']} ({item['agent_id']}, {item['file_path']}:{item['line_start'] or '-'})")
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--mr-id", default=DEFAULT_MR_ID)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    report = evaluate(conn, args.mr_id)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(report), "utf-8")
    if args.json_out:
        json_out = Path(args.json_out)
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({**report, "coverage": "<omitted>"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
