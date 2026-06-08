from __future__ import annotations

import hashlib
import re
from typing import Any

from diff.slicer import extract_added_lines
from tools.java_web_static_tool import scan_java_web_files
from tools.tool_normalizer import dedupe_tool_findings


def sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def make_finding(
    agent_id: str,
    severity: str,
    changed: Any,
    line_no: int | None,
    title: str,
    description: str,
    recommendation: str,
    evidence: str,
    head_sha: str,
    suggested_code: str | None = None,
) -> dict[str, Any]:
    confidence = {"high": 0.86, "medium": 0.78, "low": 0.68}.get(severity, 0.7)
    default_suggested_code = (
        f"// 建议修改示例：请在 {changed.filename}"
        f"{f':{line_no}' if line_no else ''} 按以下方向调整\n"
        f"// {recommendation}"
    )
    return {
        "severity": severity,
        "confidence": confidence,
        "agent_id": agent_id,
        "head_sha": head_sha,
        "dedupe_hash": sha1("|".join([agent_id, title, changed.filename, evidence.strip()[:120]])),
        "file_path": changed.filename,
        "line_start": line_no,
        "line_end": line_no,
        "title": title,
        "problem_description": description,
        "recommendation": recommendation,
        "suggested_code": (suggested_code or default_suggested_code).strip()[:4000],
        "evidence": evidence.strip()[:500],
    }


def static_findings(agent_id: str, files: list[Any], head_sha: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for changed in files:
        for line_no, text in extract_added_lines(changed.patch):
            lowered = text.lower()
            if agent_id == "security_agent":
                if "eval(" in lowered or "exec(" in lowered:
                    findings.append(make_finding(agent_id, "high", changed, line_no, "危险动态执行", "新增代码包含 eval/exec 动态执行，容易引入远程代码执行风险。", "改用白名单分发或显式函数调用，避免执行未可信输入。", text, head_sha))
                if any(token in lowered for token in ["statement.executequery(", "statement.executeupdate(", "createquery("]) and "+" in text:
                    findings.append(make_finding(agent_id, "high", changed, line_no, "SQL 拼接存在注入风险", "新增 Java 代码疑似将外部输入拼接进 SQL/JPQL 查询，可能导致注入或越权查询。", "改用 PreparedStatement、参数绑定或类型安全查询构造器，并校验输入范围。", text, head_sha))
                if re.search(r"(?i)(password|secret|token)\s*[:=]\s*['\"][^'\"]{6,}", text):
                    findings.append(make_finding(agent_id, "medium", changed, line_no, "疑似敏感信息写入代码", "新增代码出现 password 字段赋值，可能导致敏感信息进入仓库。", "改用 secret store 或环境变量注入，并确认不会打印到日志。", text, head_sha))
            elif agent_id == "coding_agent":
                if "todo" in lowered or "fixme" in lowered:
                    findings.append(make_finding(agent_id, "low", changed, line_no, "遗留 TODO 进入 MR", "新增代码包含 TODO/FIXME，可能代表未完成逻辑。", "在合入前补齐实现，或说明该 TODO 的 owner 和截止时间。", text, head_sha))
                if "except:" in lowered or "catch (error)" in lowered:
                    findings.append(make_finding(agent_id, "medium", changed, line_no, "异常处理过宽", "新增异常处理可能吞掉关键信息，影响排障和业务一致性。", "限定异常类型，记录必要上下文，并保留失败路径。", text, head_sha))
                if "catch (exception" in lowered or "catch (throwable" in lowered:
                    findings.append(make_finding(agent_id, "medium", changed, line_no, "Java 异常捕获过宽", "新增 Java 代码捕获 Exception/Throwable，容易吞掉关键失败并破坏事务或审计语义。", "捕获明确异常类型，记录上下文并保留失败传播或补偿逻辑。", text, head_sha))
                if " as any" in lowered or ": any" in lowered:
                    findings.append(make_finding(agent_id, "low", changed, line_no, "新增宽泛 any 类型", "新增代码使用 any 逃避类型约束，可能掩盖边界和兼容性问题。", "收窄类型定义，或在边界处显式解析和校验外部数据。", text, head_sha))
            elif agent_id == "performance_agent":
                if re.search(r"\b(findall|select\s+\*|query\(|fetchall\(|all\(\))", lowered):
                    findings.append(make_finding(agent_id, "medium", changed, line_no, "疑似无界查询或全量加载", "新增代码可能执行无界查询或全量加载，数据量增大时会造成延迟和内存风险。", "增加分页、limit、过滤条件或批处理边界，并评估热点路径。", text, head_sha))
                if "sleep(" in lowered or "timeout" in lowered and any(token in lowered for token in ["none", "0", "-1"]):
                    findings.append(make_finding(agent_id, "medium", changed, line_no, "外部等待或超时策略存在风险", "新增等待或超时设置可能导致阻塞、资源占用或重试放大。", "设置明确超时、重试上限和降级策略。", text, head_sha))
            elif agent_id == "ddd_agent":
                if any(token in changed.filename.lower() for token in ["domain", "entity", "aggregate"]) and any(token in lowered for token in ["dict", "any", "record<string", "json"]):
                    findings.append(make_finding(agent_id, "medium", changed, line_no, "领域对象使用弱类型承载业务概念", "领域层新增代码使用弱类型结构表达业务概念，容易让不变量散落并降低可演进性。", "提炼值对象、实体方法或领域服务，明确业务含义和不变量维护位置。", text, head_sha))
                if any(token in lowered for token in ["controller", "handler"]) and any(token in lowered for token in ["business", "domain", "rule"]):
                    findings.append(make_finding(agent_id, "medium", changed, line_no, "业务规则疑似进入入口层", "新增入口层代码承载业务规则，可能破坏应用服务和领域层边界。", "将领域规则移动到聚合、领域服务或应用服务，并由入口层只负责协议适配。", text, head_sha))
            elif agent_id == "frontend_agent":
                if "dangerouslysetinnerhtml" in lowered or "innerhtml" in lowered:
                    findings.append(make_finding(agent_id, "high", changed, line_no, "前端直接渲染 HTML", "新增代码直接渲染 HTML，可能引入 XSS 或内容污染风险。", "避免直接渲染 HTML；如必须使用，先进行可信净化并限制来源。", text, head_sha))
                if "useeffect(" in lowered and "[]" in lowered:
                    findings.append(make_finding(agent_id, "low", changed, line_no, "useEffect 空依赖需要确认闭包状态", "新增 useEffect 使用空依赖，若读取外部状态可能产生 stale state。", "确认 effect 不依赖可变状态，或补齐依赖并处理重复执行。", text, head_sha))
            elif agent_id == "redis_agent":
                if re.search(r"\bkeys\s*\(", lowered):
                    findings.append(make_finding(agent_id, "high", changed, line_no, "生产路径疑似使用 Redis KEYS", "新增 Redis KEYS 调用可能阻塞实例并影响线上可用性。", "改用 SCAN、索引集合或更精确的 key 设计，并限制批量大小。", text, head_sha))
                if re.search(r"\b(set|setex|hset)\s*\(", lowered) and not any(token in lowered for token in ["ttl", "expire", "ex=", "px=", "setex"]):
                    findings.append(make_finding(agent_id, "medium", changed, line_no, "Redis 写入缺少 TTL 信号", "新增缓存写入没有明显 TTL 或清理策略，可能造成陈旧数据或 key 膨胀。", "为缓存 key 设置 TTL，或在代码/配置中说明永久 key 的清理机制。", text, head_sha))
            elif agent_id == "test_agent":
                if changed.filename.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".java")) and changed.additions > 80 and "test" not in changed.filename.lower():
                    findings.append(make_finding(agent_id, "medium", changed, line_no, "大改动缺少测试信号", "该文件新增较多业务代码，但当前变更中没有明显测试文件对应。", "补充关键路径、边界条件或回归测试，或在 MR 描述说明已有覆盖。", text, head_sha))
                    break
    java_web_findings = [
        item
        for item in scan_java_web_files(files, head_sha)
        if item.get("agent_id") == agent_id or (agent_id == "security_agent" and item.get("agent_id") == "dependency_agent")
    ]
    return dedupe_tool_findings(findings + java_web_findings)
