from __future__ import annotations

import re
from collections import Counter
from typing import Any

from tools.candidate_store import upsert_candidate_finding
from tools.tool_normalizer import normalized_rule_category


def _line_value(finding: dict[str, Any]) -> int:
    raw = finding.get("line_start") or finding.get("line_number") or finding.get("line")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _token_jaccard(a: str, b: str) -> float:
    include_cjk = _has_cjk(a) and _has_cjk(b)
    left = _similarity_tokens(a, include_cjk=include_cjk)
    right = _similarity_tokens(b, include_cjk=include_cjk)
    if not left or not right:
        score = 0.0
    else:
        score = len(left & right) / len(left | right)
    if _has_cjk(a) or _has_cjk(b):
        score = max(score, _semantic_similarity(a, b))
    return score


def _has_cjk(value: str) -> bool:
    return re.search(r"[\u3400-\u9fff]", str(value or "")) is not None


def _similarity_tokens(value: str, *, include_cjk: bool) -> set[str]:
    tokens: set[str] = set()
    for match in re.findall(r"[a-zA-Z0-9_]+|[\u3400-\u9fff]+", str(value or "").lower()):
        if re.fullmatch(r"[\u3400-\u9fff]+", match):
            if not include_cjk:
                continue
            if len(match) == 1:
                tokens.add(match)
                continue
            for size in (2, 3):
                if len(match) < size:
                    continue
                tokens.update(match[index : index + size] for index in range(0, len(match) - size + 1))
            continue
        tokens.add(match)
    return tokens


CJK_SEMANTIC_PHRASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("权限校验", ("权限校验", "鉴权", "授权校验", "权限检查", "权限控制", "认证授权")),
    ("服务端", ("服务端", "后端", "服务器端")),
    ("客户端", ("客户端", "前端", "请求方")),
    ("客户端可控", ("客户端可控", "客户端传入", "外部传入", "外部输入", "用户输入", "请求传入", "请求参数", "外部参数")),
    ("状态变更", ("状态变更", "状态覆盖", "覆盖状态", "覆盖订单状态", "更新状态", "更新订单状态", "状态更新", "变更订单状态")),
    ("订单状态", ("订单状态", "支付状态", "业务状态")),
    ("缺少", ("缺少", "没有", "未", "无", "没有进行", "没有做", "未进行", "未做", "未校验", "未检查", "无校验")),
    ("校验", ("校验", "验证", "检查", "约束", "策略约束")),
    ("接口", ("接口", "入口", "端点", "endpoint")),
    ("管理操作", ("管理操作", "管理员操作", "管理接口", "admin")),
    ("SQL注入", ("sql注入", "sql injection", "拼接sql", "sql拼接")),
    ("注入风险", ("注入风险", "注入漏洞", "injection")),
    ("字符串拼接", ("字符串拼接", "直接拼接", "拼接", "concat")),
    ("命令执行", ("命令执行", "系统命令", "执行命令", "runtime.exec", "processbuilder")),
    ("命令注入", ("命令注入", "command injection")),
    ("文件路径", ("文件路径", "路径", "目录", "文件名", "path")),
    ("文件读取", ("文件读取", "路径读取", "读取文件", "读文件", "读取", "read file")),
    ("路径穿越", ("路径穿越", "目录穿越", "path traversal", "../")),
    ("路径规范化", ("路径规范化", "目录限制", "限制目录", "normalize", "canonical")),
    ("敏感信息", ("敏感信息", "敏感数据", "密钥", "密码", "口令", "令牌", "凭证", "token", "secret", "accesskey", "apikey", "api key")),
    ("日志输出", ("日志输出", "打印日志", "写入日志", "记录日志", "logger", "log")),
    ("日志泄露", ("日志泄露", "泄露凭证", "泄露敏感", "敏感日志")),
    ("资源关闭", ("资源关闭", "资源释放", "未关闭", "没有关闭", "try-with-resources", "文件句柄")),
    ("BigDecimal", ("bigdecimal",)),
    ("浮点数", ("double", "float", "浮点")),
    ("金额", ("金额", "价格", "费用", "total", "amount", "price")),
    ("精度问题", ("精度问题", "精度丢失", "精度风险", "精度")),
    ("返回NULL", ("return null", "返回 null", "返回null")),
    ("集合索引", ("get(0)", "首元素", "第一个", "first element", "索引访问")),
    ("空集合校验", ("isEmpty", "空集合", "集合为空")),
)

GENERIC_CJK_SEMANTIC_TOKENS = {"缺少", "校验", "服务端", "客户端", "接口"}
SEMANTIC_ACTION_TOKENS = {
    "状态变更",
    "字符串拼接",
    "SQL执行",
    "命令执行",
    "文件读取",
    "日志输出",
    "资源打开",
    "BigDecimal构造",
    "集合索引",
    "返回NULL",
}
SEMANTIC_RISK_TOKENS = {
    "SQL注入",
    "命令注入",
    "注入风险",
    "路径穿越",
    "日志泄露",
    "资源关闭",
    "精度问题",
}
SEMANTIC_OBJECT_TOKENS = {
    "客户端可控",
    "订单状态",
    "管理操作",
    "文件路径",
    "敏感信息",
    "BigDecimal",
    "浮点数",
    "金额",
}


def _cjk_semantic_tokens(value: str) -> set[str]:
    text = str(value or "").lower()
    compact = re.sub(r"\s+", "", text)
    tokens: set[str] = set()
    for canonical, variants in CJK_SEMANTIC_PHRASES:
        if any(variant.lower().replace(" ", "") in compact or variant.lower() in text for variant in variants):
            tokens.add(canonical)
    return tokens


def _code_words(value: str) -> set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    return {
        part.lower()
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", spaced)
        for part in re.split(r"[_\W]+", token)
        if part
    }


def _has_any_code_word(words: set[str], compact: str, variants: set[str]) -> bool:
    return bool(words & variants) or any(variant in compact for variant in variants if len(variant) >= 6)


def _code_semantic_tokens(value: str) -> set[str]:
    text = str(value or "")
    compact = re.sub(r"\s+", "", text).lower()
    words = _code_words(text)
    tokens: set[str] = set()

    request_words = {
        "request",
        "req",
        "param",
        "params",
        "parameter",
        "body",
        "dto",
        "input",
        "payload",
        "header",
        "cookie",
        "form",
        "pathvariable",
    }
    if _has_any_code_word(words, compact, request_words | {"getparameter", "getheader", "getcookie"}):
        tokens.add("客户端可控")

    has_sql_name = "sql" in words or "sql" in compact
    has_sql_execute = bool(re.search(r"\bexecute(query|update|largeupdate|)\s*\(", compact)) or "createstatement" in compact
    has_concat = "+" in text or ".concat(" in compact or "${" in text
    if has_sql_name and has_sql_execute and has_concat:
        tokens.add("SQL注入")
        tokens.add("注入风险")
    if has_sql_name and has_concat:
        tokens.add("字符串拼接")
    if has_sql_execute:
        tokens.add("SQL执行")

    has_command_sink = _has_any_code_word(words, compact, {"runtime", "exec", "processbuilder", "process", "command", "bash", "sh", "cmd"})
    if has_command_sink:
        tokens.add("命令执行")
    if has_command_sink and "客户端可控" in tokens and has_concat:
        tokens.add("命令注入")
        tokens.add("注入风险")

    has_file_path = _has_any_code_word(words, compact, {"path", "paths", "file", "files", "filename", "dirname", "basedir", "directory", "dir"})
    has_file_read = _has_any_code_word(words, compact, {"read", "readstring", "readallbytes", "inputstream", "fileinputstream", "reader", "bufferedreader"})
    if has_file_path:
        tokens.add("文件路径")
    if has_file_read:
        tokens.add("文件读取")
    if has_file_path and has_file_read and "客户端可控" in tokens:
        tokens.add("路径穿越")

    has_log_sink = _has_any_code_word(words, compact, {"log", "logger", "slf4j", "info", "debug", "warn", "error", "trace", "print", "println"})
    has_sensitive = _has_any_code_word(
        words,
        compact,
        {"password", "passwd", "secret", "token", "apikey", "api", "key", "credential", "accesskey", "auth", "authorization"},
    )
    if has_sensitive:
        tokens.add("敏感信息")
    if has_log_sink:
        tokens.add("日志输出")
    if has_sensitive and has_log_sink:
        tokens.add("日志泄露")

    has_resource_open = _has_any_code_word(
        words,
        compact,
        {"inputstream", "outputstream", "fileinputstream", "fileoutputstream", "reader", "writer", "connection"},
    ) or "createstatement" in compact
    if has_resource_open:
        tokens.add("资源打开")
    if has_resource_open and "try(" not in compact and ".close(" not in compact:
        tokens.add("资源关闭")
        tokens.add("缺少")

    if "bigdecimal" in words or "newbigdecimal" in compact:
        tokens.add("BigDecimal")
    if bool(words & {"double", "float"}) or ".doublevalue(" in compact or ".floatvalue(" in compact:
        tokens.add("浮点数")
    if bool(words & {"amount", "price", "money", "total", "fee", "cost"}):
        tokens.add("金额")
    if "BigDecimal" in tokens and "浮点数" in tokens:
        tokens.add("BigDecimal构造")
        tokens.add("精度问题")

    has_status_word = "status" in words or "state" in words or "setstatus" in compact or "getstatus" in compact
    if has_status_word:
        tokens.add("订单状态")
    if "setstatus" in compact or re.search(r"\b(status|state)\s*=", compact) or re.search(r"\.set[A-Za-z0-9_]*(status|state)\s*\(", compact):
        tokens.add("状态变更")

    if "returnnull" in compact:
        tokens.add("返回NULL")
    if ".get(0)" in compact or ".findfirst(" in compact or re.search(r"\[[0-9]+]", compact):
        tokens.add("集合索引")
    if ".isempty(" in compact or ".isnotempty(" in compact or ".size()>0" in compact or ".size()!=0" in compact:
        tokens.add("空集合校验")

    if _has_any_code_word(words, compact, {"admin", "manager", "management", "delete", "remove", "update"}):
        tokens.add("管理操作")
    if _has_any_code_word(words, compact, {"preauthorize", "secured", "hasrole", "hasauthority", "permission", "authorize", "authenticate"}):
        tokens.add("权限校验")

    return tokens


def _semantic_tokens(value: str) -> set[str]:
    return _cjk_semantic_tokens(value) | _code_semantic_tokens(value)


def _semantic_similarity(a: str, b: str) -> float:
    left = _semantic_tokens(a)
    right = _semantic_tokens(b)
    if not left or not right:
        return 0.0
    overlap = left & right
    if len(overlap) < 2:
        return 0.0
    if not _cjk_semantic_overlap_is_actionable(overlap):
        return 0.0
    specific_overlap = overlap - GENERIC_CJK_SEMANTIC_TOKENS
    if not specific_overlap:
        return 0.0
    if "客户端可控" in left and "客户端可控" not in overlap and not (right & {"SQL注入", "命令注入", "路径穿越"}):
        return 0.0
    dice = (2 * len(overlap)) / (len(left) + len(right))
    left_specific = left - GENERIC_CJK_SEMANTIC_TOKENS
    evidence_coverage = len(specific_overlap) / len(left_specific) if left_specific else 0.0
    return max(dice, min(1.0, evidence_coverage))


def _cjk_semantic_overlap_is_actionable(overlap: set[str]) -> bool:
    specific = overlap - GENERIC_CJK_SEMANTIC_TOKENS
    if "权限校验" in overlap and "缺少" in overlap:
        return True
    if "资源关闭" in overlap and "缺少" in overlap:
        return True
    if len(specific) < 2:
        return False
    if overlap & SEMANTIC_RISK_TOKENS:
        return bool(specific & (SEMANTIC_ACTION_TOKENS | SEMANTIC_OBJECT_TOKENS | {"注入风险"}))
    if "权限校验" in overlap:
        return "缺少" in overlap and bool(overlap & {"管理操作", "客户端可控"})
    if {"客户端可控", "状态变更"} <= overlap:
        return True
    if {"BigDecimal", "浮点数"} <= overlap:
        return True
    if {"资源关闭", "缺少"} <= overlap:
        return True
    if {"文件路径", "文件读取", "客户端可控"} <= overlap:
        return True
    if {"敏感信息", "日志输出"} <= overlap:
        return True
    return bool((specific & SEMANTIC_ACTION_TOKENS) and (specific & SEMANTIC_OBJECT_TOKENS))


def _evidence_matches_source(evidence: str, source_snippet: str) -> dict[str, Any]:
    evidence_text = str(evidence or "").strip()
    source_text = str(source_snippet or "").strip()
    if not evidence_text or not source_text:
        return {"matched": False, "score": 0.0}
    evidence_lower = evidence_text.lower()
    source_lower = source_text.lower()
    containment_score = 0.0
    if evidence_lower in source_lower or source_lower in evidence_lower:
        containment_score = 1.0
    score = max(_token_jaccard(evidence_text, source_text), containment_score)
    return {"matched": score >= 0.5, "score": round(score, 4)}


def _source_contradiction_reasons(finding: dict[str, Any], source_snippet: str) -> list[str]:
    text = " ".join(
        str(part or "")
        for part in (
            finding.get("title"),
            finding.get("problem_description"),
            finding.get("evidence"),
            finding.get("recommendation"),
        )
    ).lower()
    source = str(source_snippet or "")
    compact_source = re.sub(r"\s+", " ", source)
    source_lower = compact_source.lower()
    reasons: list[str] = []

    mentions_bigdecimal_double = (
        "bigdecimal" in text
        and any(marker in text for marker in ["double", "float", "浮点", "精度", "金额"])
        and any(marker in text for marker in ["构造", "constructor", "new bigdecimal"])
    )
    if mentions_bigdecimal_double:
        has_string_constructor = bool(re.search(r"new\s+BigDecimal\s*\(\s*['\"]", source))
        has_double_constructor = bool(
            re.search(r"new\s+BigDecimal\s*\(\s*(?:[0-9]+\.[0-9]+|[A-Za-z_][\w.]*\.doubleValue\s*\(\s*\)|[A-Za-z_][\w.]*Double[A-Za-z_]*|double\s+[A-Za-z_])", source)
        )
        if has_string_constructor and not has_double_constructor:
            reasons.append("source_contradicts_bigdecimal_double_constructor")

    mentions_return_null = any(marker in text for marker in ["return null", "返回 null", "返回null", "map 返回 null", "集合返回 null"])
    if mentions_return_null and "return null" not in source_lower:
        reasons.append("source_contradicts_return_null")

    mentions_first_without_empty_guard = any(
        marker in text
        for marker in ["首元素", "第一个", "first element", "get(0)", "findfirst", "未判空", "未判断为空", "未检查为空"]
    )
    if mentions_first_without_empty_guard and re.search(r"\b(isEmpty|isNotEmpty)\s*\(", source) and re.search(r"\.get\s*\(\s*0\s*\)", source):
        reasons.append("source_has_empty_guard_for_first_element")

    mentions_no_try_with_resources = any(
        marker in text
        for marker in ["未关闭", "没有关闭", "未使用 try-with-resources", "resource leak", "资源泄漏"]
    )
    if mentions_no_try_with_resources and re.search(r"try\s*\([^)]*(InputStream|OutputStream|Connection|Statement|ResultSet|Reader|Writer)", source):
        reasons.append("source_has_try_with_resources")

    return reasons


def _source_has_rule_signal(finding: dict[str, Any], source_snippet: str) -> bool:
    source = str(source_snippet or "").lower()
    rules = set(_rule_ids_for(finding))
    categories = {normalized_rule_category(rule, finding.get("title")) for rule in rules}
    text = " ".join(
        str(part or "")
        for part in (finding.get("title"), finding.get("problem_description"), finding.get("evidence"))
    ).lower()
    compact = re.sub(r"\s+", " ", source)
    if "SQL_INJECTION" in categories:
        has_sql_execution = any(marker in compact for marker in ["executequery", "executeupdate", "createstatement", "statement.execute"])
        has_concat = bool(re.search(r'["\'][^"\']*\b(select|update|delete|insert)\b[^"\']*["\']\s*\+', compact)) or bool(
            re.search(r"\+\s*[a-zA-Z_][\w.]*", compact)
        )
        mentions_sql_risk = any(marker in text for marker in ["sql", "注入", "injection", "拼接"])
        if has_sql_execution and has_concat and mentions_sql_risk:
            return True
    if "MYBATIS_SQL_INJECTION" in categories:
        if "${" in compact and any(marker in text for marker in ["mybatis", "sql", "注入", "injection", "${"]):
            return True
    if "SECRET_LEAK" in categories:
        if re.search(r"(password|passwd|secret|token|apikey|api_key|accesskey)\s*[:=]", compact):
            return True
    if "REDIS_KEYS_COMMAND" in categories or "REDIS-CMD-003" in rules:
        if re.search(r"\bkeys\s*\(", compact) or ".keys(" in compact:
            return True
    if "SPRING_ACTUATOR_EXPOSED" in categories or "SEC-CONFIG-007" in rules:
        return "management" in compact and "endpoints" in compact and "exposure" in compact and re.search(r"include\s*:\s*['\"]?\*", compact) is not None
    return False


def _with_flag(finding: dict[str, Any], flag: str) -> dict[str, Any]:
    flags = list(finding.get("verification_flags") or [])
    if flag not in flags:
        flags.append(flag)
    return {**finding, "verification_flags": flags}


def _rule_ids_for(finding: dict[str, Any]) -> list[str]:
    raw_values: list[Any] = [
        finding.get("rule_id"),
        finding.get("tool_rule_id"),
        finding.get("normalized_rule_category"),
    ]
    raw_values.extend(finding.get("covered_rules") or [])
    result: list[str] = []
    for raw in raw_values:
        value = str(raw or "").strip()
        if value and value not in result:
            result.append(value)
    return result


def _platform_rule_ids_for(finding: dict[str, Any]) -> list[str]:
    raw_values: list[Any] = [finding.get("rule_id"), finding.get("normalized_rule_category")]
    raw_values.extend(finding.get("covered_rules") or [])
    result: list[str] = []
    for raw in raw_values:
        value = str(raw or "").strip()
        if value and value not in result:
            result.append(value)
    return result


def _requires_source_evidence(finding: dict[str, Any]) -> bool:
    category = str(finding.get("normalized_rule_category") or "")
    rule_ids = set(_rule_ids_for(finding))
    mr_level_categories = {"MISSING_TEST_COVERAGE"}
    mr_level_rules = {"TEST-COVER-001", "JOLT_JAVA_MISSING_TEST"}
    return category not in mr_level_categories and not (rule_ids & mr_level_rules)


def _has_tool_observation_support(
    finding: dict[str, Any],
    tool_observations: list[dict[str, Any]],
    *,
    line_tolerance: int,
) -> bool:
    file_path = str(finding.get("file_path") or "")
    line_no = _line_value(finding)
    finding_rules = set(_rule_ids_for(finding))
    finding_categories = {normalized_rule_category(rule, finding.get("title")) for rule in finding_rules}
    for observation in tool_observations:
        if str(observation.get("file_path") or "") != file_path:
            continue
        obs_line = _line_value(observation)
        same_line = line_no <= 0 or obs_line <= 0 or abs(obs_line - line_no) <= line_tolerance
        obs_rule = str(observation.get("rule_id") or "")
        same_rule = obs_rule in finding_rules or normalized_rule_category(obs_rule, observation.get("message")) in finding_categories
        if same_line and same_rule:
            return True
    return False


def verify_candidate_findings(
    findings: list[dict[str, Any]],
    valid_files: set[str],
    agent_config_by_id: dict[str, dict[str, Any]],
    suppressed_hashes: set[str],
    diff_hunks: dict[str, list[tuple[int, int]]] | None = None,
    rule_registry: set[str] | None = None,
    source_snippet_loader: Any | None = None,
    tool_observations: list[dict[str, Any]] | None = None,
    line_tolerance: int = 3,
    min_evidence_jaccard: float = 0.5,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    diff_hunks = diff_hunks or {}
    rule_registry = rule_registry or set()
    tool_observations = tool_observations or []

    for finding in findings:
        reasons: list[str] = []
        file_path = str(finding.get("file_path") or "")
        if file_path not in valid_files:
            reasons.append("file_not_found")
        line_no = _line_value(finding)
        if file_path in valid_files and line_no > 0 and diff_hunks:
            hunks = diff_hunks.get(file_path, [])
            if hunks and not any(start - line_tolerance <= line_no <= end + line_tolerance for start, end in hunks):
                reasons.append("line_out_of_diff")
        evidence = str(finding.get("evidence") or "").strip()
        if (
            file_path in valid_files
            and evidence
            and line_no > 0
            and source_snippet_loader is not None
            and _requires_source_evidence(finding)
        ):
            source_snippet = source_snippet_loader(file_path, line_no, window=5)
            contradiction_reasons = _source_contradiction_reasons(finding, source_snippet)
            reasons.extend(contradiction_reasons)
        if (
            file_path in valid_files
            and evidence
            and line_no > 0
            and source_snippet_loader is not None
            and _requires_source_evidence(finding)
            and not reasons
            and not _has_tool_observation_support(finding, tool_observations, line_tolerance=line_tolerance)
        ):
            source_snippet = source_snippet_loader(file_path, line_no, window=5)
            evidence_signal = "\n".join(
                str(part or "").strip()
                for part in (evidence, finding.get("title"), finding.get("problem_description"))
                if str(part or "").strip()
            )
            evidence_match = _evidence_matches_source(evidence_signal, source_snippet)
            evidence_score = float(evidence_match["score"])
            source_rule_signal = _source_has_rule_signal(finding, source_snippet)
            source_location_supported = bool(str(source_snippet or "").strip()) or source_rule_signal
            if evidence_score < min_evidence_jaccard:
                penalty = 0.05 if evidence_score >= 0.2 else 0.08
                flags = ["low_evidence_match"]
                if source_location_supported:
                    flags.append("source_location_supported")
                else:
                    flags.append("source_window_missing")
                for flag in flags:
                    finding = _with_flag(finding, flag)
                finding = {
                    **finding,
                    "confidence": max(0.0, float(finding.get("confidence") or 0) - penalty),
                    "evidence_match_score": evidence_score,
                }
        rule_ids = _platform_rule_ids_for(finding)
        if rule_registry and rule_ids and not any(rule_id in rule_registry for rule_id in rule_ids):
            finding = _with_flag(finding, "unknown_rule")
        confidence = float(finding.get("confidence") or 0)
        config = agent_config_by_id.get(str(finding.get("agent_id") or ""), {})
        verification_flags = set(finding.get("verification_flags") or [])
        if confidence < float(config.get("min_confidence", 0.7)) and "low_evidence_match" not in verification_flags:
            reasons.append("below_confidence")
        if finding.get("dedupe_hash") in suppressed_hashes:
            reasons.append("suppressed_by_feedback")
        if not finding.get("title") or not finding.get("problem_description"):
            reasons.append("schema_invalid")
        if reasons:
            rejected.append({**finding, "rejected_reasons": reasons})
            continue
        accepted.append(finding)

    return accepted, rejected


def rejected_reason_counts(rejected: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for item in rejected:
        counter.update(str(reason) for reason in item.get("rejected_reasons") or [])
    return dict(counter)


def make_verify_findings_node(
    *,
    conn: Any,
    recorder: Any,
    job: Any,
    project_id: str,
    run_id: str,
    agent_config_by_id: dict[str, dict[str, Any]],
    load_feedback_suppressions: Any,
    load_feedback_boosts: Any,
    verify_findings: Any,
    load_tool_observations: Any,
):
    def verify_findings_node(state: dict[str, Any]) -> dict[str, Any]:
        files = state["files"]
        all_findings = state["all_findings"]
        conn.execute("UPDATE review_jobs SET status = 'judging', heartbeat_at = CURRENT_TIMESTAMP WHERE id = %s", (job["id"],))
        conn.execute(
            "UPDATE merge_requests SET review_status = 'judging' WHERE id = %s AND review_status NOT IN ('merged', 'closed')",
            (job["merge_request_id"],),
        )
        conn.commit()
        verifier_span = recorder.span("verify_findings", "verifier")
        suppressed_hashes = load_feedback_suppressions(conn, project_id)
        boosted_hashes = load_feedback_boosts(conn, project_id)
        tool_observations = state.get("tool_observations") or load_tool_observations(conn, run_id)
        verification_result = verify_findings(
            recorder,
            verifier_span,
            all_findings,
            files,
            agent_config_by_id,
            suppressed_hashes,
            boosted_hashes,
            tool_observations,
            state.get("source_file_contents") or {},
        )
        if isinstance(verification_result, tuple):
            verified_findings, verifier_rejections = verification_result
        else:
            verified_findings = verification_result
            verifier_rejections = [item for item in all_findings if item.get("rejected_reasons")]
        accepted_hashes = {str(item.get("dedupe_hash") or "") for item in verified_findings}
        for finding in all_findings:
            dedupe_hash = str(finding.get("dedupe_hash") or "")
            if dedupe_hash in accepted_hashes:
                upsert_candidate_finding(
                    conn,
                    review_run_id=run_id,
                    item=finding,
                    stage="verifier",
                    status="accepted",
                )
        for finding in verifier_rejections:
            upsert_candidate_finding(
                conn,
                review_run_id=run_id,
                item=finding,
                stage="verifier",
                status="rejected",
                rejected_reasons=finding.get("rejected_reasons") or [],
            )
        conn.commit()
        recorder.event(
            verifier_span,
            "finding_verified",
            f"Verifier 接收 {len(all_findings)} 个候选，保留 {len(verified_findings)} 个",
            {
                "input": len(all_findings),
                "accepted": len(verified_findings),
                "tool_observation_count": len(tool_observations),
                "suppressed_feedback_count": len(suppressed_hashes),
                "boosted_feedback_count": len(boosted_hashes),
                "rejected": len(verifier_rejections),
                "rejected_reason_counts": rejected_reason_counts(verifier_rejections),
            },
        )
        recorder.finish(verifier_span)
        return {
            **state,
            "verified_findings": verified_findings,
            "verifier_rejections": verifier_rejections,
            "candidate_quality": {
                **(state.get("candidate_quality") or {}),
                "expert_candidate_count": len(all_findings),
                "verifier_accepted_count": len(verified_findings),
                "verifier_rejected_count": len(verifier_rejections),
                "verifier_rejected_reason_counts": rejected_reason_counts(verifier_rejections),
            },
        }

    return verify_findings_node
