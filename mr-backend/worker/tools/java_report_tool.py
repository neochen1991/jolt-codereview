from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


JAVA_TOOL_AGENT_BY_TYPE = {
    "spotbugs": "coding_agent",
    "findsecbugs": "security_agent",
    "pmd": "coding_agent",
    "p3c": "coding_agent",
    "checkstyle": "coding_agent",
    "error-prone": "coding_agent",
    "error_prone": "coding_agent",
    "nullaway": "coding_agent",
    "jacoco": "test_agent",
    "archunit": "ddd_agent",
    "flyway": "database_agent",
    "liquibase": "database_agent",
    "openapi-diff": "backend_agent",
    "oasdiff": "backend_agent",
    "codeql": "security_agent",
    "snyk": "dependency_agent",
    "dependency-check": "dependency_agent",
    "osv": "dependency_agent",
    "semgrep": "security_agent",
}

RULE_AGENT_HINTS = {
    "sql": "security_agent",
    "inject": "security_agent",
    "xss": "security_agent",
    "secret": "security_agent",
    "password": "security_agent",
    "auth": "security_agent",
    "cve": "dependency_agent",
    "dependency": "dependency_agent",
    "license": "dependency_agent",
    "notnull": "database_agent",
    "drop": "database_agent",
    "migration": "database_agent",
    "coverage": "test_agent",
    "jacoco": "test_agent",
    "archunit": "ddd_agent",
}

def parse_report(report_path: Path, report_kind: str) -> dict[str, Any]:
    if not report_path.exists():
        return {"tool": report_kind, "status": "requires_report", "findings": []}
    try:
        content = report_path.read_text("utf-8")
        report_format = "json" if report_path.suffix.lower() == ".json" else "xml"
        return parse_external_report_payload(report_kind, report_format, content)
    except OSError as exc:
        return {"tool": report_kind, "status": "failed", "error": f"{type(exc).__name__}: {exc}", "findings": []}


def parse_external_report_payload(report_type: str, report_format: str, payload: Any) -> dict[str, Any]:
    tool = _normalize_tool(report_type)
    fmt = (report_format or "").lower().strip()
    content = _payload_content(payload)
    try:
        if fmt in {"sarif", "sarif-json"} or _looks_like_sarif(content):
            data = _json_payload(content)
            findings = _parse_sarif(tool, data)
        elif fmt in {"json", "dependency-check", "osv", "snyk"}:
            data = _json_payload(content)
            findings = _parse_json_report(tool, data)
        elif fmt in {"xml", "pmd", "checkstyle", "spotbugs", "findsecbugs", "jacoco"} or str(content).lstrip().startswith("<"):
            root = ET.fromstring(str(content))
            root_name = _strip_ns(root.tag).lower()
            if tool in {"pmd", "p3c"} or root_name == "pmd":
                findings = _parse_pmd_xml(tool, root)
            elif tool in {"checkstyle", "error-prone", "error_prone", "nullaway"} or root_name == "checkstyle":
                findings = _parse_checkstyle_xml(tool, root)
            elif tool in {"spotbugs", "findsecbugs"} or root_name in {"bugcollection", "buginstance"}:
                findings = _parse_spotbugs_xml(tool, root)
            elif tool == "jacoco" or root_name == "report":
                findings = _parse_jacoco_xml(tool, root)
            else:
                findings = []
        else:
            findings = _parse_text_report(tool, str(content))
        return {"tool": tool, "status": "completed", "findings": findings, "finding_count": len(findings)}
    except (json.JSONDecodeError, ET.ParseError, TypeError, ValueError) as exc:
        return {"tool": tool, "status": "failed", "error": f"{type(exc).__name__}: {exc}", "findings": []}


def parse_pmd(report_path: Path) -> dict[str, Any]:
    return parse_report(report_path, "pmd")


def parse_checkstyle(report_path: Path) -> dict[str, Any]:
    return parse_report(report_path, "checkstyle")


def parse_spotbugs(report_path: Path) -> dict[str, Any]:
    return parse_report(report_path, "spotbugs")


def parse_jacoco(report_path: Path) -> dict[str, Any]:
    return parse_report(report_path, "jacoco")


def _parse_pmd_xml(tool: str, root: ET.Element) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for file_node in root.iter():
        if _strip_ns(file_node.tag).lower() != "file":
            continue
        file_path = str(file_node.attrib.get("name") or file_node.attrib.get("filename") or "")
        for violation in file_node:
            if _strip_ns(violation.tag).lower() != "violation":
                continue
            rule_id = str(violation.attrib.get("rule") or violation.attrib.get("class") or "PMD")
            line = _to_int(violation.attrib.get("beginline") or violation.attrib.get("line"))
            end_line = _to_int(violation.attrib.get("endline")) or line
            priority = _to_int(violation.attrib.get("priority")) or 3
            findings.append(_finding(tool, rule_id, file_path, line, end_line, _pmd_severity(priority), violation.text or rule_id))
    return findings


def _parse_checkstyle_xml(tool: str, root: ET.Element) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for file_node in root.iter():
        if _strip_ns(file_node.tag).lower() != "file":
            continue
        file_path = str(file_node.attrib.get("name") or "")
        for error in file_node:
            if _strip_ns(error.tag).lower() != "error":
                continue
            rule_id = str(error.attrib.get("source") or error.attrib.get("rule") or tool)
            line = _to_int(error.attrib.get("line"))
            severity = _severity(error.attrib.get("severity"))
            message = str(error.attrib.get("message") or rule_id)
            findings.append(_finding(tool, rule_id, file_path, line, line, severity, message))
    return findings


def _parse_spotbugs_xml(tool: str, root: ET.Element) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for bug in root.iter():
        if _strip_ns(bug.tag).lower() != "buginstance":
            continue
        rule_id = str(bug.attrib.get("type") or bug.attrib.get("abbrev") or tool)
        priority = _to_int(bug.attrib.get("priority"))
        severity = "high" if priority and priority <= 1 else "medium" if priority and priority <= 3 else "low"
        message = _first_child_text(bug, "LongMessage") or _first_child_text(bug, "ShortMessage") or rule_id
        source = _first_child(bug, "SourceLine")
        file_path = ""
        line = None
        end_line = None
        if source is not None:
            file_path = str(source.attrib.get("sourcepath") or source.attrib.get("sourcefile") or "")
            line = _to_int(source.attrib.get("start"))
            end_line = _to_int(source.attrib.get("end")) or line
        findings.append(_finding(tool, rule_id, file_path, line, end_line, severity, message))
    return findings


def _parse_jacoco_xml(tool: str, root: ET.Element) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for package in root.iter():
        if _strip_ns(package.tag).lower() != "package":
            continue
        package_name = str(package.attrib.get("name") or "").replace(".", "/")
        for sourcefile in package:
            if _strip_ns(sourcefile.tag).lower() != "sourcefile":
                continue
            file_path = "/".join([part for part in [package_name, str(sourcefile.attrib.get("name") or "")] if part])
            uncovered = [
                _to_int(line.attrib.get("nr"))
                for line in sourcefile
                if _strip_ns(line.tag).lower() == "line"
                and (_to_int(line.attrib.get("mi")) or 0) > 0
                and (_to_int(line.attrib.get("ci")) or 0) == 0
            ]
            uncovered = [line for line in uncovered if line]
            if uncovered:
                findings.append(
                    _finding(
                        tool,
                        "TEST-COVER-001",
                        file_path,
                        uncovered[0],
                        uncovered[-1],
                        "medium",
                        f"JaCoCo 显示新增代码存在未覆盖行：{', '.join(map(str, uncovered[:20]))}",
                    )
                )
    return findings


def _parse_sarif(tool: str, data: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        return findings
    rule_levels: dict[str, str] = {}
    for run in data.get("runs", []) if isinstance(data.get("runs"), list) else []:
        if not isinstance(run, dict):
            continue
        driver = (run.get("tool") or {}).get("driver") if isinstance(run.get("tool"), dict) else {}
        for rule in driver.get("rules", []) if isinstance(driver.get("rules"), list) else []:
            if isinstance(rule, dict):
                rule_id = str(rule.get("id") or rule.get("name") or "")
                default_config = rule.get("defaultConfiguration") if isinstance(rule.get("defaultConfiguration"), dict) else {}
                if rule_id and default_config.get("level"):
                    rule_levels[rule_id] = _severity(default_config.get("level"))
        for result in run.get("results", []) if isinstance(run.get("results"), list) else []:
            if not isinstance(result, dict):
                continue
            rule_id = str(result.get("ruleId") or result.get("rule") or tool)
            message_obj = result.get("message") if isinstance(result.get("message"), dict) else {}
            message = str(message_obj.get("text") or message_obj.get("markdown") or rule_id)
            severity = _severity(result.get("level")) if result.get("level") else rule_levels.get(rule_id, "medium")
            location = _primary_sarif_location(result)
            findings.append(_finding(tool, rule_id, location["file_path"], location["line"], location["end_line"], severity, message))
    return findings


def _parse_json_report(tool: str, data: Any) -> list[dict[str, Any]]:
    if _looks_like_sarif(data):
        return _parse_sarif(tool, data)
    normalized_tool = _normalize_tool(tool)
    if normalized_tool == "dependency-check":
        return _parse_dependency_check_json(tool, data)
    if normalized_tool in {"osv", "osv-scanner"}:
        return _parse_osv_json(tool, data)
    if normalized_tool == "trivy":
        return _parse_trivy_json(tool, data)
    if normalized_tool == "kics":
        return _parse_kics_json(tool, data)
    if normalized_tool in {"openapi-diff", "oasdiff"}:
        return _parse_openapi_diff_json(tool, data)
    rows = []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        for key in ["findings", "results", "vulnerabilities", "dependencies", "violations", "issues"]:
            value = data.get(key)
            if isinstance(value, list):
                rows = value
                break
    findings: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rule_id = str(row.get("ruleId") or row.get("rule_id") or row.get("rule") or row.get("id") or row.get("vulnerability") or tool)
        file_path = str(row.get("file") or row.get("file_path") or row.get("path") or row.get("filename") or row.get("component") or "")
        line = _to_int(row.get("line") or row.get("line_start") or row.get("startLine") or row.get("StartLine"))
        end_line = _to_int(row.get("line_end") or row.get("endLine") or row.get("EndLine")) or line
        severity = _severity(row.get("severity") or row.get("level") or row.get("priority"))
        message = str(row.get("message") or row.get("description") or row.get("title") or rule_id)
        findings.append(_finding(tool, rule_id, file_path, line, end_line, severity, message))
    return findings


def _parse_dependency_check_json(tool: str, data: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    dependencies = data.get("dependencies", []) if isinstance(data, dict) else []
    for dependency in dependencies if isinstance(dependencies, list) else []:
        if not isinstance(dependency, dict):
            continue
        file_path = str(dependency.get("filePath") or dependency.get("fileName") or "pom.xml")
        vulns = dependency.get("vulnerabilities") if isinstance(dependency.get("vulnerabilities"), list) else []
        for vuln in vulns:
            if not isinstance(vuln, dict):
                continue
            cve = str(vuln.get("name") or vuln.get("cve") or vuln.get("source") or "dependency-vulnerability")
            severity = _severity(vuln.get("severity"))
            description = str(vuln.get("description") or vuln.get("title") or cve)
            package_name = str(dependency.get("fileName") or dependency.get("filePath") or "dependency")
            findings.append(_finding(tool, cve, file_path, None, None, severity, f"{package_name}: {description}"))
    return findings


def _parse_osv_json(tool: str, data: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    results = data.get("results", []) if isinstance(data, dict) else []
    for result in results if isinstance(results, list) else []:
        if not isinstance(result, dict):
            continue
        source = result.get("source") if isinstance(result.get("source"), dict) else {}
        file_path = str(source.get("path") or source.get("file") or "pom.xml")
        packages = result.get("packages") if isinstance(result.get("packages"), list) else []
        for package in packages:
            if not isinstance(package, dict):
                continue
            package_info = package.get("package") if isinstance(package.get("package"), dict) else {}
            package_name = str(package_info.get("name") or package.get("name") or "dependency")
            package_version = str(package_info.get("version") or package.get("version") or "")
            vulns = package.get("vulnerabilities") if isinstance(package.get("vulnerabilities"), list) else []
            for vuln in vulns:
                if not isinstance(vuln, dict):
                    continue
                aliases = vuln.get("aliases") if isinstance(vuln.get("aliases"), list) else []
                vuln_id = str(vuln.get("id") or (aliases[0] if aliases else "osv"))
                severity = _osv_severity(vuln)
                summary = str(vuln.get("summary") or vuln.get("details") or vuln_id)
                component = f"{package_name}:{package_version}" if package_version else package_name
                findings.append(_finding(tool, vuln_id, file_path, None, None, severity, f"{component}: {summary}"))
    return findings


def _parse_trivy_json(tool: str, data: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    results = data.get("Results", []) if isinstance(data, dict) else []
    for result in results if isinstance(results, list) else []:
        if not isinstance(result, dict):
            continue
        target = str(result.get("Target") or "")
        for vuln in result.get("Vulnerabilities", []) if isinstance(result.get("Vulnerabilities"), list) else []:
            if not isinstance(vuln, dict):
                continue
            vuln_id = str(vuln.get("VulnerabilityID") or vuln.get("ID") or "trivy-vulnerability")
            package_name = str(vuln.get("PkgName") or vuln.get("PkgID") or "dependency")
            installed_version = str(vuln.get("InstalledVersion") or "")
            fixed_version = str(vuln.get("FixedVersion") or "")
            component = f"{package_name}:{installed_version}" if installed_version else package_name
            fix = f" fixed={fixed_version}" if fixed_version else ""
            message = f"{component}{fix}: {str(vuln.get('Title') or vuln.get('Description') or vuln_id)}"
            finding = _finding(tool, vuln_id, target, None, None, _severity(vuln.get("Severity")), message)
            finding["raw_artifact_id"] = "|".join(part for part in [package_name, installed_version, vuln_id] if part)
            findings.append(finding)
        for misconfig in result.get("Misconfigurations", []) if isinstance(result.get("Misconfigurations"), list) else []:
            if not isinstance(misconfig, dict):
                continue
            rule_id = str(misconfig.get("ID") or misconfig.get("AVDID") or "trivy-misconfiguration")
            message = str(misconfig.get("Title") or misconfig.get("Message") or rule_id)
            cause = misconfig.get("CauseMetadata") if isinstance(misconfig.get("CauseMetadata"), dict) else {}
            line = _to_int(cause.get("StartLine"))
            findings.append(_finding(tool, rule_id, target, line, _to_int(cause.get("EndLine")) or line, _severity(misconfig.get("Severity")), message))
        for secret in result.get("Secrets", []) if isinstance(result.get("Secrets"), list) else []:
            if not isinstance(secret, dict):
                continue
            rule_id = str(secret.get("RuleID") or "trivy-secret")
            line = _to_int(secret.get("StartLine"))
            findings.append(_finding(tool, rule_id, target, line, _to_int(secret.get("EndLine")) or line, "high", str(secret.get("Title") or rule_id)))
    return findings


def _parse_kics_json(tool: str, data: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    queries = data.get("queries", []) if isinstance(data, dict) else []
    for query in queries if isinstance(queries, list) else []:
        if not isinstance(query, dict):
            continue
        rule_id = str(query.get("query_id") or query.get("query_name") or "kics")
        severity = _severity(query.get("severity"))
        files = query.get("files") if isinstance(query.get("files"), list) else []
        for file_item in files:
            if not isinstance(file_item, dict):
                continue
            file_path = str(file_item.get("file_name") or file_item.get("file_path") or "")
            line = _to_int(file_item.get("line"))
            message = str(file_item.get("issue_type") or query.get("query_name") or rule_id)
            findings.append(_finding(tool, rule_id, file_path, line, line, severity, message))
    return findings


def _parse_openapi_diff_json(tool: str, data: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        return findings
    file_path = str(data.get("newSpec") or data.get("new_spec") or data.get("head") or "openapi.yaml")
    rows: list[Any] = []
    for key in ["breakingDifferences", "breaking_differences", "incompatible", "differences", "changes"]:
        value = data.get(key)
        if isinstance(value, list):
            rows.extend(value)
    for row in rows:
        if not isinstance(row, dict):
            continue
        breaking = bool(row.get("breaking") or row.get("breakingChange") or row.get("incompatible"))
        rule_id = str(row.get("code") or row.get("id") or row.get("type") or "OPENAPI_DIFF")
        path = str(row.get("path") or row.get("jsonPath") or row.get("endpoint") or "")
        message = str(row.get("message") or row.get("description") or row.get("action") or rule_id)
        severity = "high" if breaking else "medium"
        findings.append(_finding(tool, rule_id, file_path, None, None, severity, f"{path} {message}".strip()))
    return findings


def _parse_text_report(tool: str, content: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    pattern = re.compile(r"(?P<file>[\w./\\-]+):(?P<line>\d+).*?(?P<rule>[A-Za-z0-9_.:-]+)?\s*(?P<msg>.+)")
    for raw in content.splitlines():
        match = pattern.match(raw.strip())
        if not match:
            continue
        rule_id = match.group("rule") or tool
        line = _to_int(match.group("line"))
        findings.append(_finding(tool, rule_id, match.group("file"), line, line, "medium", match.group("msg")))
    return findings


def _finding(
    tool: str,
    rule_id: str,
    file_path: str,
    line_start: int | None,
    line_end: int | None,
    severity: str,
    message: str,
) -> dict[str, Any]:
    agent_id = _agent_for(tool, rule_id, message)
    title = f"{tool} 命中：{rule_id}"
    return {
        "agent_id": agent_id,
        "severity": severity,
        "confidence": 0.88 if severity in {"critical", "high"} else 0.8 if severity == "medium" else 0.72,
        "tool_name": tool,
        "tool_rule_id": rule_id,
        "covered_rules": [rule_id] if _is_project_rule(rule_id) else [],
        "file_path": _normalize_path(file_path),
        "line_start": line_start,
        "line_end": line_end or line_start,
        "title": title,
        "problem_description": message.strip()[:1000],
        "recommendation": _recommendation(tool, rule_id, message),
        "suggested_code": _suggested_code(tool, rule_id),
        "evidence": message.strip()[:500] or rule_id,
    }


def _payload_content(payload: Any) -> Any:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ["content", "report", "raw", "text", "xml", "json", "sarif"]:
            if key in payload:
                return payload[key]
    return payload


def _json_payload(content: Any) -> Any:
    if isinstance(content, (dict, list)):
        return content
    return json.loads(str(content or "{}"))


def _looks_like_sarif(content: Any) -> bool:
    if isinstance(content, dict):
        return str(content.get("version") or "").startswith("2.") and isinstance(content.get("runs"), list)
    text = str(content or "").lstrip()
    return '"runs"' in text[:1000] and '"version"' in text[:1000] and "sarif" in text[:2000].lower()


def _primary_sarif_location(result: dict[str, Any]) -> dict[str, Any]:
    locations = result.get("locations") if isinstance(result.get("locations"), list) else []
    if not locations:
        return {"file_path": "", "line": None, "end_line": None}
    physical = locations[0].get("physicalLocation") if isinstance(locations[0], dict) else {}
    artifact = physical.get("artifactLocation") if isinstance(physical, dict) and isinstance(physical.get("artifactLocation"), dict) else {}
    region = physical.get("region") if isinstance(physical, dict) and isinstance(physical.get("region"), dict) else {}
    return {
        "file_path": str(artifact.get("uri") or ""),
        "line": _to_int(region.get("startLine")),
        "end_line": _to_int(region.get("endLine")) or _to_int(region.get("startLine")),
    }


def _agent_for(tool: str, rule_id: str, message: str) -> str:
    lowered = f"{tool} {rule_id} {message}".lower()
    for hint, agent_id in RULE_AGENT_HINTS.items():
        if hint in lowered:
            return agent_id
    return JAVA_TOOL_AGENT_BY_TYPE.get(_normalize_tool(tool), "coding_agent")


def _normalize_tool(tool: str) -> str:
    return re.sub(r"\s+", "-", (tool or "external-java-report").strip().lower())


def _normalize_path(file_path: str) -> str:
    value = file_path.replace("\\", "/")
    for marker in ["/src/main/", "/src/test/", "/pom.xml", "/build.gradle"]:
        if marker in value:
            idx = value.find(marker)
            return value[idx + 1 :]
    return value.lstrip("./")


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _first_child(parent: ET.Element, name: str) -> ET.Element | None:
    for child in parent:
        if _strip_ns(child.tag) == name:
            return child
    return None


def _first_child_text(parent: ET.Element, name: str) -> str:
    child = _first_child(parent, name)
    return (child.text or "").strip() if child is not None else ""


def _to_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _severity(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"critical", "blocker", "error", "high", "1"}:
        return "high" if raw != "critical" else "critical"
    if raw in {"warning", "warn", "medium", "moderate", "2", "3"}:
        return "medium"
    return "low"


def _osv_severity(vuln: dict[str, Any]) -> str:
    severities = vuln.get("severity") if isinstance(vuln.get("severity"), list) else []
    for item in severities:
        if not isinstance(item, dict):
            continue
        score = str(item.get("score") or "").upper()
        if "CRITICAL" in score:
            return "critical"
        if "HIGH" in score:
            return "high"
        if "MEDIUM" in score or "MODERATE" in score:
            return "medium"
    return "medium"


def _pmd_severity(priority: int) -> str:
    if priority <= 1:
        return "high"
    if priority <= 3:
        return "medium"
    return "low"


def _is_project_rule(rule_id: str) -> bool:
    return bool(re.match(r"^[A-Z]+[A-Z0-9_-]*-\d{3}(:[A-Z0-9_-]+)?$", rule_id or ""))


def _recommendation(tool: str, rule_id: str, message: str) -> str:
    lowered = f"{tool} {rule_id} {message}".lower()
    if "sql" in lowered and "inject" in lowered:
        return "改用参数绑定、白名单字段映射或类型安全查询构造器，并补充注入回归测试。"
    if "cve" in lowered or "dependency" in lowered:
        return "升级到无漏洞版本，必要时移除传递依赖，并在依赖锁定文件中记录收敛结果。"
    if "coverage" in lowered or "jacoco" in lowered:
        return "补充覆盖新增分支、异常路径和边界值的单元测试或集成测试。"
    if "drop" in lowered or "not null" in lowered:
        return "改为兼容式 migration，先新增可空列和回填，再分阶段收紧约束或删除旧字段。"
    return "按静态工具命中规则修复代码，并保留对应测试或配置证明。"


def _suggested_code(tool: str, rule_id: str) -> str:
    return (
        f"// {tool}:{rule_id} 建议修改示例\n"
        "// 1. 在命中行附近按工具规则修改实现\n"
        "// 2. 保留必要的单元测试、集成测试或配置证据\n"
        "// 3. 重新运行对应静态工具确认该规则不再命中"
    )
