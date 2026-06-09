from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB = "data/jolt-codereview.sqlite"
DEFAULT_OUT = "docs/reports/2026-06-09-pr5-pr6-quality-after-stage1.md"

PR5_MR = "mr_repo_3a83959a2dc948d6_3823778428"
PR6_MR = "mr_repo_3a83959a2dc948d6_3823779359"


PR5_GROUND_TRUTH = [
    {"id": "PR5-01", "title": "Hardcoded risk admin key", "files": ["DynamicRiskPolicyService.java"], "patterns": [r"(ADMIN_KEY|risk-admin-2026|硬编码|密钥)", r"(轮换|泄露|管理密钥|secret)"]},
    {"id": "PR5-02", "title": "Admin key passed in query parameter", "files": ["DynamicRiskPolicyController.java"], "patterns": [r"(adminKey|RequestParam|查询参数|URL)", r"(日志|代理|访问日志|泄露|密钥)"]},
    {"id": "PR5-03", "title": "User-controlled SpEL expression execution", "files": ["DynamicRiskPolicyService.java"], "patterns": [r"(SpelExpressionParser|parseExpression|expression|SpEL)", r"(注入|任意方法|执行|用户|外部)"]},
    {"id": "PR5-04", "title": "StandardEvaluationContext exposes PaymentOrder", "files": ["DynamicRiskPolicyService.java"], "patterns": [r"(StandardEvaluationContext|EvaluationContext|根对象)", r"(PaymentOrder|order|完整对象|领域对象)", r"(暴露|访问|攻击面|超出|敏感)"]},
    {"id": "PR5-05", "title": "Request-controlled pluginClassName reflection", "files": ["DynamicRiskPolicyService.java", "DynamicRiskPolicyController.java"], "patterns": [r"(pluginClassName|Class\.forName|反射)", r"(外部|请求|任意类|加载|实例化)"]},
    {"id": "PR5-06", "title": "Plugin load failure defaults to allow", "files": ["DynamicRiskPolicyService.java"], "patterns": [r"(插件|plugin|Class\.forName|order\s*->\s*false)", r"(默认放行|fail.?open|失败.*放行|安全失败|降级)"]},
    {"id": "PR5-07", "title": "Static HashMap policy cache is not thread safe", "files": ["DynamicRiskPolicyService.java"], "patterns": [r"(POLICY_CACHE|HashMap|static|静态)", r"(线程安全|并发|ConcurrentHashMap|共享状态)"]},
    {"id": "PR5-08", "title": "Fixed active cache key causes merchant overwrite", "files": ["DynamicRiskPolicyService.java"], "patterns": [r"(\"active\"|active|POLICY_CACHE|缓存)", r"(商户|租户|覆盖|复用|串用|隔离)"]},
    {"id": "PR5-09", "title": "lastPolicy global state pollutes tenants", "files": ["DynamicRiskPolicyService.java"], "patterns": [r"(lastPolicy|静态|static|全局)", r"(商户|租户|跨请求|状态污染|共享)"]},
    {"id": "PR5-10", "title": "paymentId miss falls back to findAll first order", "files": ["DynamicRiskPolicyService.java"], "patterns": [r"(findAll|findFirst|orElseGet|回退|fallback)", r"(paymentId|订单|无关|其他商户|第一笔)"]},
    {"id": "PR5-11", "title": "evaluate does not verify merchant ownership", "files": ["DynamicRiskPolicyService.java", "DynamicRiskPolicyController.java"], "patterns": [r"(merchantId|paymentId|订单|PaymentOrder)", r"(归属|越权|IDOR|多租户|校验|授权)"]},
    {"id": "PR5-12", "title": "previewForMerchant leaks global payment summary", "files": ["DynamicRiskPolicyService.java"], "patterns": [r"(previewForMerchant|findAll|totalLoaded|firstPaymentId)", r"(泄露|全局|跨商户|所有订单|内存)"]},
    {"id": "PR5-13", "title": "preview returns active policy from another merchant", "files": ["DynamicRiskPolicyService.java"], "patterns": [r"(previewForMerchant|POLICY_CACHE|get\(\"active\"\)|activePolicy)", r"(策略|商户|暴露|跨商户|租户)"]},
    {"id": "PR5-14", "title": "java.util.Random used for risk sampling", "files": ["DynamicRiskPolicyService.java"], "patterns": [r"(Random|RANDOM|nextInt|sampleBucket|采样)", r"(安全|不可预测|风控|决策|SecureRandom)"]},
    {"id": "PR5-15", "title": "SecureRandom initialized with fixed seed", "files": ["DynamicRiskPolicyService.java"], "patterns": [r"(SecureRandom|SECURE_RANDOM|setSeed|固定种子)", r"(可预测|reviewToken|随机|token)"]},
    {"id": "PR5-16", "title": "BigDecimal equals scale mismatch", "files": ["DynamicRiskPolicyService.java"], "patterns": [r"(BigDecimal|equals|1000\\.0|金额)", r"(scale|精度|compareTo|误判|相等)"]},
    {"id": "PR5-17", "title": "Default SpEL expression expands executable surface", "files": ["DynamicRiskPolicyService.java"], "patterns": [r"(new java\\.math\\.BigDecimal|默认表达式|SpEL|expression)", r"(攻击面|执行能力|构造|方法调用|限制)"]},
    {"id": "PR5-18", "title": "lastPolicyAgeSeconds can NPE", "files": ["DynamicRiskPolicyService.java"], "patterns": [r"(lastPolicyAgeSeconds|lastPolicy|getUpdatedAt|null)", r"(NPE|空指针|null|未保存策略)"]},
    {"id": "PR5-19", "title": "Policy priority is stored but ignored", "files": ["DynamicRiskPolicy.java", "DynamicRiskPolicyService.java"], "patterns": [r"(priority|getPriority|优先级)", r"(未使用|未参与|排序|选择|形同虚设)"]},
    {"id": "PR5-20", "title": "Risk policy APIs lack real authz/audit approval", "files": ["DynamicRiskPolicyController.java", "DynamicRiskPolicyService.java"], "patterns": [r"(risk-policies|savePolicy|evaluate|接口|API)", r"(认证|授权|审计|审批|权限)"]},
]


PR6_GROUND_TRUTH = [
    {"id": "PR6-01", "title": "ObjectInputStream readObject unsafe deserialization", "files": ["SettlementArchiveService.java"], "patterns": [r"(ObjectInputStream|readObject|反序列化)", r"(不安全|白名单|外部|请求体|deserialization)"]},
    {"id": "PR6-02", "title": "Serializable command lacks whitelist/version/full validation", "files": ["ArchiveImportCommand.java", "SettlementArchiveService.java"], "patterns": [r"(ArchiveImportCommand|Serializable|serialVersionUID|命令对象)", r"(白名单|版本|字段校验|反序列化|validation)"]},
    {"id": "PR6-03", "title": "ZipEntry name path traversal", "files": ["SettlementArchiveService.java"], "patterns": [r"(ZipEntry|getName|Zip Slip|路径穿越)", r"(normalize|目标路径|拼接|校验|destination)"]},
    {"id": "PR6-04", "title": "Destination request parameter allows arbitrary write directory", "files": ["ArchiveImportController.java", "SettlementArchiveService.java"], "patterns": [r"(destination|outputDir|目标目录|请求参数)", r"(任意|可控|写入|目录|路径)"]},
    {"id": "PR6-05", "title": "ZIP extraction lacks size/count/ratio limits", "files": ["SettlementArchiveService.java"], "patterns": [r"(ZipInputStream|ZIP|解压|Zip Bomb|压缩比)", r"(大小|数量|总大小|限制|上限)"]},
    {"id": "PR6-06", "title": "ZIP extraction does not reject symlink or special file", "files": ["SettlementArchiveService.java"], "patterns": [r"(ZipEntry|符号链接|symlink|特殊文件)", r"(校验|拒绝|覆盖|非预期)"]},
    {"id": "PR6-07", "title": "mkdirs return value ignored", "files": ["SettlementArchiveService.java"], "patterns": [r"(mkdirs|getParentFile|目录创建)", r"(返回值|失败|检查|继续)"]},
    {"id": "PR6-08", "title": "ZipInputStream not closed by try-with-resources", "files": ["SettlementArchiveService.java"], "patterns": [r"(ZipInputStream|try-with-resources|close|资源)", r"(未关闭|释放|异常路径|泄漏)"]},
    {"id": "PR6-09", "title": "User-controlled regex can cause ReDoS", "files": ["SettlementArchiveService.java"], "patterns": [r"(Pattern\\.compile|matches|filter|正则|regex)", r"(ReDoS|回溯|用户可控|灾难)"]},
    {"id": "PR6-10", "title": "payments.findAll filtered in memory", "files": ["SettlementArchiveService.java"], "patterns": [r"(payments\\.findAll|findAll|内存过滤|全表)", r"(分页|数据库过滤|性能|内存)"]},
    {"id": "PR6-11", "title": "CSV fields are not escaped", "files": ["SettlementArchiveService.java"], "patterns": [r"(CSV|csv|append|customerId|merchantId)", r"(逗号|换行|引号|转义|损坏)"]},
    {"id": "PR6-12", "title": "CSV formula injection", "files": ["SettlementArchiveService.java"], "patterns": [r"(CSV|Excel|公式)", r"(=|\\+|-|@|前缀字符|formula)", r"(注入|转义|防护|字段)"]},
    {"id": "PR6-13", "title": "Content-Disposition filename not sanitized", "files": ["SettlementArchiveService.java"], "patterns": [r"(Content-Disposition|setHeader|filename|safeLookingName)", r"(净化|响应头|header|注入|下载名)"]},
    {"id": "PR6-14", "title": "fileName lacks separator/control/length validation", "files": ["SettlementArchiveService.java", "ArchiveImportController.java"], "patterns": [r"(fileName|safeLookingName|文件名)", r"(路径分隔符|控制字符|超长|长度|校验|限制)"]},
    {"id": "PR6-15", "title": "outputDir allows arbitrary path write", "files": ["SettlementArchiveService.java"], "patterns": [r"(outputDir|Path\\.of|writeString|写文件)", r"(任意路径|可控|目录|写入)"]},
    {"id": "PR6-16", "title": "Default charset used for CSV IO", "files": ["SettlementArchiveService.java"], "patterns": [r"(getBytes\(\)|writeString|charset|字符集|编码)", r"(默认|未指定|UTF-8|环境|不一致)"]},
    {"id": "PR6-17", "title": "LocalDateTime.now lacks audit clock/zone", "files": ["SettlementArchiveService.java"], "patterns": [r"(LocalDateTime\\.now|exportedAt|时间)", r"(时区|Clock|审计|跨区域|歧义)"]},
    {"id": "PR6-18", "title": "Predictable temp filename", "files": ["SettlementArchiveService.java"], "patterns": [r"(java\\.io\\.tmpdir|last-settlement|tmp|临时文件)", r"(可预测|覆盖|竞态|泄露|Files\\.createTempFile)"]},
    {"id": "PR6-19", "title": "Corrections lack null/range/count validation", "files": ["SettlementArchiveService.java", "ArchiveImportCommand.java"], "patterns": [r"(corrections|金额|批量|adjustments)", r"(null|范围|数量|校验|NPE|异常数据)"]},
    {"id": "PR6-20", "title": "Archive import/export APIs lack authz and ownership", "files": ["ArchiveImportController.java", "SettlementArchiveService.java"], "patterns": [r"(archive|import|export|导入|导出|接口)", r"(认证|授权|权限|归属|商户|越权)"]},
]


SUITES = {
    PR5_MR: {"name": "PR5 dynamic risk policy", "ground_truth": PR5_GROUND_TRUTH},
    PR6_MR: {"name": "PR6 archive import/export", "ground_truth": PR6_GROUND_TRUTH},
}


def load_json(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except json.JSONDecodeError:
        return fallback


def latest_completed_run(conn: sqlite3.Connection, mr_id: str, run_id: str | None = None) -> sqlite3.Row:
    if run_id:
        row = conn.execute("SELECT * FROM review_runs WHERE id = ?", (run_id,)).fetchone()
    else:
        row = conn.execute(
            """
            SELECT rr.*
            FROM review_runs rr
            JOIN review_jobs rj ON rj.id = rr.review_job_id
            WHERE rj.merge_request_id = ?
              AND rr.status IN ('waiting_confirmation', 'completed')
            ORDER BY rr.started_at DESC
            LIMIT 1
            """,
            (mr_id,),
        ).fetchone()
    if not row:
        raise SystemExit(f"completed review run not found for MR: {mr_id}")
    return row


def finding_text(row: sqlite3.Row) -> str:
    keys = [
        "title",
        "problem_description",
        "recommendation",
        "evidence",
        "suggested_code",
        "file_path",
        "covered_rules_json",
    ]
    return "\n".join(str(row[key] or "") for key in keys)


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
        "line_end": row["line_end"],
        "title": row["title"],
        "covered_rules": load_json(row["covered_rules_json"], []),
        "tool_provenance": load_json(row["tool_provenance_json"], []),
    }


def semantic_key(row: sqlite3.Row) -> tuple[str, str, int]:
    title = re.sub(r"\s+", "", str(row["title"] or "").lower())
    rules = ",".join(load_json(row["covered_rules_json"], []))
    line = int(row["line_start"] or 0)
    line_bucket = ((line - 1) // 3) * 3 + 1 if line > 0 else 0
    return (rules or title[:28], str(row["file_path"] or ""), line_bucket)


def tool_observation_summary(conn: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    rows = conn.execute("SELECT * FROM tool_observations WHERE review_run_id = ? ORDER BY tool_name, file_path, line_start", (run_id,)).fetchall()
    by_state: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    for row in rows:
        by_state[str(row["adoption_state"] or "candidate")] = by_state.get(str(row["adoption_state"] or "candidate"), 0) + 1
        by_rule[str(row["rule_id"] or row["tool_name"])] = by_rule.get(str(row["rule_id"] or row["tool_name"]), 0) + 1
    return {
        "count": len(rows),
        "by_state": by_state,
        "by_rule": by_rule,
    }


def evaluate_suite(conn: sqlite3.Connection, mr_id: str, suite: dict[str, Any], run_id: str | None = None) -> dict[str, Any]:
    run = latest_completed_run(conn, mr_id, run_id)
    findings = conn.execute("SELECT * FROM review_findings WHERE review_run_id = ? ORDER BY severity DESC, confidence DESC", (run["id"],)).fetchall()
    coverage: list[dict[str, Any]] = []
    matched_finding_ids: set[str] = set()
    for spec in suite["ground_truth"]:
        matches = [row for row in findings if matches_spec(row, spec)]
        if matches:
            matched_finding_ids.add(str(matches[0]["id"]))
        coverage.append(
            {
                "id": spec["id"],
                "title": spec["title"],
                "matched": bool(matches),
                "matches": [summarize(row) for row in matches[:5]],
            }
        )
    matched_count = sum(1 for item in coverage if item["matched"])
    duplicate_count = max(0, len(findings) - len({semantic_key(row) for row in findings}))
    unmapped_rows = [row for row in findings if str(row["id"]) not in matched_finding_ids and not any(matches_spec(row, spec) for spec in suite["ground_truth"])]
    false_positive_count = max(0, len(unmapped_rows) - duplicate_count)
    recall = matched_count / len(suite["ground_truth"]) if suite["ground_truth"] else 0.0
    false_positive_rate = false_positive_count / len(findings) if findings else 0.0
    return {
        "mr_id": mr_id,
        "name": suite["name"],
        "run_id": run["id"],
        "status": run["status"],
        "started_at": run["started_at"],
        "completed_at": run["completed_at"],
        "expected_count": len(suite["ground_truth"]),
        "finding_count": len(findings),
        "matched_count": matched_count,
        "missing_count": len(suite["ground_truth"]) - matched_count,
        "recall": round(recall, 4),
        "false_positive_count": false_positive_count,
        "false_positive_rate": round(false_positive_rate, 4),
        "duplicate_count": duplicate_count,
        "budget": load_json(run["budget_used_json"], {}),
        "coverage_json": load_json(run["coverage_json"], {}),
        "tool_observations": tool_observation_summary(conn, run["id"]),
        "meets_target": recall >= 0.9 and false_positive_rate <= 0.1,
        "coverage": coverage,
        "unmapped_findings": [summarize(row) for row in unmapped_rows[:30]],
    }


def render_markdown(reports: list[dict[str, Any]]) -> str:
    total_expected = sum(item["expected_count"] for item in reports)
    total_matched = sum(item["matched_count"] for item in reports)
    total_findings = sum(item["finding_count"] for item in reports)
    total_fp = sum(item["false_positive_count"] for item in reports)
    overall_recall = total_matched / total_expected if total_expected else 0.0
    overall_fp = total_fp / total_findings if total_findings else 0.0
    lines = [
        "# PR5 / PR6 Review Quality Report After Stage 1",
        "",
        f"- Overall Recall: {overall_recall:.4f} ({total_matched}/{total_expected})",
        f"- Overall False Positive Rate: {overall_fp:.4f} ({total_fp}/{total_findings})",
        f"- Meets 90/10 Target: {'yes' if overall_recall >= 0.9 and overall_fp <= 0.1 and all(r['meets_target'] for r in reports) else 'no'}",
        "",
        "| PR | Run | Findings | Matched | Missing | Recall | FP | FP Rate | Tool Obs | Target |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for report in reports:
        lines.append(
            f"| {report['name']} | `{report['run_id']}` | {report['finding_count']} | {report['matched_count']} | "
            f"{report['missing_count']} | {report['recall']:.4f} | {report['false_positive_count']} | "
            f"{report['false_positive_rate']:.4f} | {report['tool_observations']['count']} | "
            f"{'yes' if report['meets_target'] else 'no'} |"
        )
    for report in reports:
        quality = report.get("coverage_json", {}).get("candidate_quality", {})
        lines.extend(
            [
                "",
                f"## {report['name']}",
                "",
                f"- Status: {report['status']}",
                f"- Candidate Quality: `{json.dumps(quality, ensure_ascii=False)}`",
                f"- Tool Observation States: `{json.dumps(report['tool_observations']['by_state'], ensure_ascii=False)}`",
                f"- Tool Rules Hit: `{json.dumps(report['tool_observations']['by_rule'], ensure_ascii=False)}`",
                "",
                "| ID | Expected Issue | Status | Best Match |",
                "| --- | --- | --- | --- |",
            ]
        )
        for item in report["coverage"]:
            best = item["matches"][0] if item["matches"] else None
            match = f"{best['title']} ({best['agent_id']}, {best['file_path']}:{best['line_start'] or '-'})" if best else "-"
            lines.append(f"| {item['id']} | {item['title']} | {'matched' if item['matched'] else 'missing'} | {match} |")
        lines.extend(["", "Unmapped final findings:"])
        if report["unmapped_findings"]:
            for row in report["unmapped_findings"]:
                lines.append(f"- {row['title']} ({row['agent_id']}, {row['file_path']}:{row['line_start'] or '-'})")
        else:
            lines.append("- None")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--json-out", default="")
    parser.add_argument("--pr5-run-id", default="")
    parser.add_argument("--pr6-run-id", default="")
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    reports = [
        evaluate_suite(conn, PR5_MR, SUITES[PR5_MR], args.pr5_run_id or None),
        evaluate_suite(conn, PR6_MR, SUITES[PR6_MR], args.pr6_run_id or None),
    ]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(reports), encoding="utf-8")
    payload = {
        "reports": reports,
        "overall": {
            "recall": round(sum(item["matched_count"] for item in reports) / sum(item["expected_count"] for item in reports), 4),
            "false_positive_rate": round(sum(item["false_positive_count"] for item in reports) / sum(item["finding_count"] for item in reports), 4),
        },
    }
    if args.json_out:
        json_out = Path(args.json_out)
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
