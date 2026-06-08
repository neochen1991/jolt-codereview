from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedRule:
    rule_id: str
    title: str
    severity: str
    applies_to: str
    check: str
    evidence_required: str

    def to_prompt_item(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "severity": self.severity,
            "applies_to": self.applies_to,
            "check": self.check,
            "evidence_required": self.evidence_required,
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
                "severity": "medium",
                "applies_to": "**/*",
                "check": "",
                "evidence_required": "changed line and concrete evidence",
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
    evidence_required = str(raw.get("evidence_required") or "").strip()
    if not evidence_required:
        evidence_required = _join_sections(sections, ["输出要求"]) or "精确文件、行号、代码证据、触发规则、影响说明和建议修改代码"
    return ParsedRule(
        rule_id=str(raw["rule_id"]),
        title=str(raw["title"]),
        severity=str(raw.get("severity", "medium")),
        applies_to=str(raw.get("applies_to", "**/*")),
        check=_compact(check, 900),
        evidence_required=_compact(evidence_required, 300),
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


def _compact(text: str, limit: int) -> str:
    compacted = re.sub(r"\s+", " ", text).strip()
    return compacted[:limit]
