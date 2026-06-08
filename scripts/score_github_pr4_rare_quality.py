from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB = "data/jolt-codereview.sqlite"
DEFAULT_MR = "mr_repo_3a83959a2dc948d6_3822556257"


GROUND_TRUTH = [
    {"id": "P4-01", "title": "Static HashMap is not thread safe", "files": ["RareIssueAuditService.java"], "patterns": [r"(HashMap|AUDIT_CACHE|static HashMap)", r"(线程安全|并发|ConcurrentHashMap|共享状态)"]},
    {"id": "P4-02", "title": "Static audit cache lacks TTL/capacity/tenant cleanup", "files": ["RareIssueAuditService.java"], "patterns": [r"(AUDIT_CACHE|缓存|cache)", r"(TTL|容量|上限|租户|清理|expire|maximumSize|内存)"]},
    {"id": "P4-03", "title": "ThreadLocal set without remove", "files": ["RareIssueAuditService.java"], "patterns": [r"(ThreadLocal|CURRENT_OPERATOR)", r"(remove|清理|泄漏|线程复用|finally)"]},
    {"id": "P4-04", "title": "Static SimpleDateFormat is not thread safe", "files": ["RareIssueAuditService.java"], "patterns": [r"(SimpleDateFormat|WINDOW_FORMAT)", r"(线程安全|DateTimeFormatter|并发)"]},
    {"id": "P4-05", "title": "BigDecimal constructed from double", "files": ["RareIssueAuditService.java"], "patterns": [r"(BigDecimal|doubleValue|double|roundedFee|fee)", r"(精度|valueOf|二进制|舍入)"]},
    {"id": "P4-06", "title": "Idempotency window uses LocalDateTime/system timezone", "files": ["RareIssueAuditService.java"], "patterns": [r"(LocalDateTime\.now|LocalDate\.now|idempotencyWindow|businessDate|系统默认时区)", r"(时区|ZoneId|Clock|Instant|夏令时|漂移|幂等)"]},
    {"id": "P4-07", "title": "SHA-1 weak signature algorithm", "files": ["RareIssueAuditService.java"], "patterns": [r"(SHA-1|SHA1|MessageDigest)", r"(弱|HmacSHA256|签名|摘要|collision|碰撞)"]},
    {"id": "P4-08", "title": "String.equals timing side channel for signature", "files": ["RareIssueAuditService.java"], "patterns": [r"(signature\.equals|String\.equals|equals\(expectedSignature|普通 String\.equals)", r"(常量时间|MessageDigest\.isEqual|timing|时序)"]},
    {"id": "P4-09", "title": "Trusts X-Forwarded-For directly", "files": ["RareIssueAuditService.java"], "patterns": [r"X-Forwarded-For", r"(可信代理|proxy|伪造|信任|RemoteAddr|Header)"]},
    {"id": "P4-10", "title": "Sensitive payment/signature logging", "files": ["RareIssueAuditService.java"], "patterns": [r"(log\.info|日志|logging|Logger)", r"(signature|amount|customer|支付|金额)", r"(敏感|泄露|脱敏|mask|signature)"]},
    {"id": "P4-11", "title": "Raw new Thread per request", "files": ["RareIssueAuditService.java"], "patterns": [r"(new Thread|ThreadPoolExecutor|Executor|线程)", r"(背压|生命周期|线程池|有界|request)"]},
    {"id": "P4-12", "title": "Background thread reads request ThreadLocal", "files": ["RareIssueAuditService.java"], "patterns": [r"(CURRENT_OPERATOR\.get|ThreadLocal|后台线程|new Thread)", r"(跨线程|不可靠|显式传参|脏数据|stale)"]},
    {"id": "P4-13", "title": "JDBC Connection/Statement/ResultSet leak", "files": ["RareAuditJdbcGateway.java"], "patterns": [r"(Connection|Statement|ResultSet|JDBC)", r"(未关闭|try-with-resources|close|泄漏|连接池)"]},
    {"id": "P4-14", "title": "autoCommit false not restored/committed/rolled back", "files": ["RareAuditJdbcGateway.java"], "patterns": [r"(autoCommit|setAutoCommit|commit|rollback)", r"(恢复|连接池|污染|事务|rollback|commit)"]},
    {"id": "P4-15", "title": "JDBC write swallows all exceptions", "files": ["RareAuditJdbcGateway.java"], "patterns": [r"writeBalanceAdjustment", r"(catch|Exception|ignored|异常)", r"(吞|静默|成功|流水|一致|回滚)"]},
    {"id": "P4-16", "title": "Mutable object used as HashMap key", "files": ["MutableTenantKey.java", "RareIssueAuditService.java"], "patterns": [r"(MutableTenantKey|rotateOperator|hashCode|equals|HashMap|AUDIT_CACHE)", r"(可变|Map key|缓存命中|hashCode|清理|破坏)"]},
    {"id": "P4-17", "title": "lastErrors returns internal mutable list", "files": ["RareIssueAuditService.java", "RareIssueAuditController.java"], "patterns": [r"(lastErrors|LAST_ERRORS)", r"(内部可变|返回.*List|篡改|immutable|copy|List\.copyOf|防御性)"]},
    {"id": "P4-18", "title": "Debug endpoint exposes internal state", "files": ["RareIssueAuditController.java", "RareIssueAuditService.java"], "patterns": [r"(debug|debugState|lastSignature|cacheSize)", r"(暴露|内部状态|调试|生产|授权|脱敏)"]},
    {"id": "P4-19", "title": "bulkAdjust has no request size limit", "files": ["RareIssueAuditController.java", "RareIssueAuditService.java"], "patterns": [r"(bulkAdjust|amounts|List<BigDecimal>|批量)", r"(规模|数量|上限|超大|长事务|内存|数据库压力)"]},
    {"id": "P4-20", "title": "Transactional self invocation", "files": ["RareIssueAuditService.java"], "patterns": [r"(selfInvokedAdjustment|@Transactional|bulkAdjust)", r"(自调用|proxy|代理|事务|失效|传播)"]},
]

KNOWN_VALID_EXTRA_PATTERNS = [
    r"(SQL|sql|注入|PreparedStatement)",
    r"(认证|授权|权限|越权)",
    r"(Bean Validation|@Valid|RequestBody)",
    r"(测试|回归|coverage|覆盖)",
]


def load_json(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except json.JSONDecodeError:
        return fallback


def latest_run(conn: sqlite3.Connection, mr_id: str, run_id: str | None) -> sqlite3.Row:
    if run_id:
        row = conn.execute("SELECT * FROM review_runs WHERE id = ?", (run_id,)).fetchone()
    else:
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
        raise SystemExit("review run not found")
    return row


def finding_text(row: sqlite3.Row, *, include_artifacts: bool = True) -> str:
    keys = [
        "title",
        "problem_description",
        "recommendation",
        "evidence",
        "suggested_code",
        "file_path",
        "covered_rules_json",
    ]
    if include_artifacts:
        keys.extend(["tool_provenance_json", "source_observations_json"])
    return "\n".join(str(row[key] or "") for key in keys)


def matches_spec(row: sqlite3.Row, spec: dict[str, Any], *, include_artifacts: bool = True) -> bool:
    text = finding_text(row, include_artifacts=include_artifacts)
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
        "line_end": row["line_end"],
        "title": row["title"],
        "covered_rules": load_json(row["covered_rules_json"], []),
    }


def semantic_key(row: sqlite3.Row) -> tuple[str, str, int]:
    rules = ",".join(load_json(row["covered_rules_json"], []))
    title = str(row["title"] or "")
    file_path = str(row["file_path"] or "")
    line = int(row["line_start"] or 0)
    return (rules or title, file_path, ((line - 1) // 5) * 5 + 1 if line > 0 else 0)


def evaluate(conn: sqlite3.Connection, run: sqlite3.Row) -> dict[str, Any]:
    findings = conn.execute("SELECT * FROM review_findings WHERE review_run_id = ? ORDER BY created_at", (run["id"],)).fetchall()
    matched_finding_ids: set[str] = set()
    coverage: list[dict[str, Any]] = []
    for spec in GROUND_TRUTH:
        direct_matches = [row for row in findings if matches_spec(row, spec, include_artifacts=False)]
        matches = direct_matches or [row for row in findings if matches_spec(row, spec)]
        if matches:
            matched_finding_ids.update(str(row["id"]) for row in matches)
        coverage.append(
            {
                "id": spec["id"],
                "title": spec["title"],
                "matched": bool(matches),
                "matches": [summarize(row) for row in matches[:5]],
            }
        )

    extra_rows = [row for row in findings if str(row["id"]) not in matched_finding_ids]
    valid_extra = [
        row
        for row in extra_rows
        if any(re.search(pattern, finding_text(row), re.IGNORECASE | re.MULTILINE) for pattern in KNOWN_VALID_EXTRA_PATTERNS)
    ]
    duplicate_count = max(0, len(findings) - len({semantic_key(row) for row in findings}))
    false_positive_count = max(0, len(extra_rows) - len(valid_extra) - duplicate_count)
    recall = sum(1 for item in coverage if item["matched"]) / len(GROUND_TRUTH)
    false_positive_rate = false_positive_count / len(findings) if findings else 0.0
    duplicate_rate = duplicate_count / len(findings) if findings else 0.0
    budget = load_json(run["budget_used_json"], {})
    return {
        "run_id": run["id"],
        "status": run["status"],
        "started_at": run["started_at"],
        "completed_at": run["completed_at"],
        "expected_count": len(GROUND_TRUTH),
        "finding_count": len(findings),
        "matched_count": sum(1 for item in coverage if item["matched"]),
        "missing_count": sum(1 for item in coverage if not item["matched"]),
        "recall": round(recall, 4),
        "false_positive_count": false_positive_count,
        "false_positive_rate": round(false_positive_rate, 4),
        "duplicate_count": duplicate_count,
        "duplicate_rate": round(duplicate_rate, 4),
        "valid_extra_count": len(valid_extra),
        "meets_target": recall >= 0.9 and false_positive_rate <= 0.1,
        "budget": budget,
        "coverage": coverage,
        "valid_extras": [summarize(row) for row in valid_extra],
        "unexplained_extras": [summarize(row) for row in extra_rows if row not in valid_extra][:20],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# GitHub PR4 Rare Issue Quality Report",
        "",
        f"- Run: `{report['run_id']}`",
        f"- Status: {report['status']}",
        f"- Recall: {report['recall']:.4f} ({report['matched_count']}/{report['expected_count']})",
        f"- False Positive Rate: {report['false_positive_rate']:.4f}",
        f"- Duplicate Rate: {report['duplicate_rate']:.4f}",
        f"- Meets Target: {'yes' if report['meets_target'] else 'no'}",
        "",
        "| ID | Expected Issue | Status | Best Match |",
        "| --- | --- | --- | --- |",
    ]
    for item in report["coverage"]:
        best = item["matches"][0] if item["matches"] else None
        match = f"{best['title']} ({best['agent_id']}, {best['file_path']}:{best['line_start'] or '-'})" if best else "-"
        lines.append(f"| {item['id']} | {item['title']} | {'matched' if item['matched'] else 'missing'} | {match} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--mr-id", default=DEFAULT_MR)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    run = latest_run(conn, args.mr_id, args.run_id or None)
    report = evaluate(conn, run)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_markdown(report), encoding="utf-8")


if __name__ == "__main__":
    main()
