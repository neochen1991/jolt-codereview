from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedRule:
    rule_id: str
    title: str
    category: str
    severity: str
    applies_to: str
    check: str
    required_evidence: str
    positive_examples: str
    negative_examples: str
    false_positive_patterns: str
    fix_guidance: str

    def to_prompt_item(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "category": self.category,
            "severity": self.severity,
            "applies_to": self.applies_to,
            "check": self.check,
            "required_evidence": self.required_evidence,
            "evidence_required": self.required_evidence,
            "positive_examples": self.positive_examples,
            "negative_examples": self.negative_examples,
            "false_positive_patterns": self.false_positive_patterns,
            "fix_guidance": self.fix_guidance,
        }


HEADING_RE = re.compile(r"^##\s+([A-Za-z0-9_-]+)\s+(.+)$")
FIELD_RE = re.compile(r"^-\s*([a-zA-Z_]+):\s*(.*)$")
SECTION_RE = re.compile(r"^###\s+(.+)$")


def parse_markdown_rules(content: str) -> list[ParsedRule]:
    rules: list[ParsedRule] = []
    current: dict[str, str | list[str]] | None = None

    def flush() -> None:
        nonlocal current
        if not current:
            return
        rule = _to_rule(current)
        if rule.check:
            rules.append(rule)
        current = None

    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        heading = HEADING_RE.match(line)
        if heading:
            flush()
            current = {
                "rule_id": heading.group(1),
                "title": heading.group(2).strip(),
                "category": "general",
                "severity": "medium",
                "applies_to": "**/*",
                "check": "",
                "required_evidence": "",
                "evidence_required": "",
                "positive_examples": "",
                "negative_examples": "",
                "false_positive_patterns": "",
                "fix_guidance": "",
                "body": [],
            }
            continue
        if not current:
            continue
        field = FIELD_RE.match(line.strip())
        if field:
            current[field.group(1).strip()] = field.group(2).strip()
        else:
            body = current.setdefault("body", [])
            if isinstance(body, list):
                body.append(line)
    flush()
    return rules


def _to_rule(raw: dict[str, str | list[str]]) -> ParsedRule:
    body = raw.get("body", [])
    sections = _extract_sections(body if isinstance(body, list) else [])
    check = str(raw.get("check") or "").strip()
    if not check:
        check = _join_sections(sections, ["规范说明", "检查点", "如何检查"])
    required_evidence = str(raw.get("required_evidence") or raw.get("evidence_required") or "").strip()
    if not required_evidence:
        required_evidence = (
            _join_sections(sections, ["证据要求", "输出要求"])
            or "精确文件、行号、代码证据、触发规则、影响说明和建议修改代码"
        )
    positive_examples = str(raw.get("positive_examples") or "").strip() or _join_sections(sections, ["正例", "正确示例"])
    negative_examples = str(raw.get("negative_examples") or "").strip() or _join_sections(sections, ["反例", "错误示例"])
    false_positive_patterns = str(raw.get("false_positive_patterns") or "").strip() or _join_sections(sections, ["误报模式", "误报排除", "例外"])
    fix_guidance = str(raw.get("fix_guidance") or "").strip() or _join_sections(sections, ["修复建议", "整改建议"])
    return ParsedRule(
        rule_id=str(raw["rule_id"]),
        title=str(raw["title"]),
        category=str(raw.get("category", "general")),
        severity=str(raw.get("severity", "medium")),
        applies_to=str(raw.get("applies_to", "**/*")),
        check=_compact(check),
        required_evidence=_compact(required_evidence),
        positive_examples=_compact(positive_examples),
        negative_examples=_compact(negative_examples),
        false_positive_patterns=_compact(false_positive_patterns),
        fix_guidance=_compact(fix_guidance),
    )


def _extract_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = ""
    for raw in lines:
        line = raw.strip()
        section = SECTION_RE.match(line)
        if section:
            current = section.group(1).strip()
            sections.setdefault(current, [])
            continue
        if current and line:
            sections[current].append(line)
    return sections


def _join_sections(sections: dict[str, list[str]], names: list[str]) -> str:
    chunks: list[str] = []
    for name in names:
        values = sections.get(name) or []
        if values:
            chunks.append(f"{name}：{' '.join(values)}")
    return "\n".join(chunks)


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
