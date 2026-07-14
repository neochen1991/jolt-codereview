from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedSkillCheckpoint:
    skill_key: str
    checkpoint_id: str
    title: str
    severity: str
    applies_to: str
    check: str
    required_evidence: str
    false_positive_patterns: str
    positive_examples: str
    negative_examples: str
    skip_conditions: str
    fix_guidance: str
    source_path: str
    parse_quality: str = "structured"

    def to_prompt_item(self) -> dict:
        return {
            "skill_key": self.skill_key,
            "checkpoint_id": self.checkpoint_id,
            "rule_id": self.checkpoint_id,
            "title": self.title,
            "severity": self.severity,
            "applies_to": self.applies_to,
            "check": self.check,
            "required_evidence": self.required_evidence,
            "evidence_required": self.required_evidence,
            "false_positive_patterns": self.false_positive_patterns,
            "positive_examples": self.positive_examples,
            "negative_examples": self.negative_examples,
            "skip_conditions": self.skip_conditions,
            "fix_guidance": self.fix_guidance,
            "source_path": self.source_path,
            "parse_quality": self.parse_quality,
        }


CHECKPOINT_HEADING_RE = re.compile(
    r"^##\s+(?:checkpoint[:：]\s*)?([A-Za-z][A-Za-z0-9_.:-]*-[A-Za-z0-9_.:-]+|[A-Z]{2,}[A-Z0-9_-]*-\d+[A-Z0-9_-]*)\s+(.+)$",
    re.IGNORECASE,
)
FIELD_RE = re.compile(r"^-\s*([a-zA-Z_]+):\s*(.*)$")
SECTION_RE = re.compile(r"^###\s+(.+)$")


def parse_skill_checkpoints(skill_key: str, content: str, *, source_path: str = "SKILL.md") -> list[dict]:
    checkpoints: list[ParsedSkillCheckpoint] = []
    current: dict[str, str | list[str]] | None = None

    def flush() -> None:
        nonlocal current
        if not current:
            return
        checkpoint = _to_checkpoint(skill_key, current, source_path)
        if checkpoint.check:
            checkpoints.append(checkpoint)
        current = None

    for raw_line in str(content or "").splitlines():
        line = raw_line.rstrip()
        heading = CHECKPOINT_HEADING_RE.match(line)
        if heading:
            flush()
            current = {
                "checkpoint_id": heading.group(1).strip(),
                "title": heading.group(2).strip(),
                "severity": "medium",
                "applies_to": "**/*",
                "check": "",
                "required_evidence": "",
                "evidence_required": "",
                "false_positive_patterns": "",
                "positive_examples": "",
                "negative_examples": "",
                "skip_conditions": "",
                "fix_guidance": "",
                "body": [],
            }
            continue
        if not current:
            continue
        field = FIELD_RE.match(line.strip())
        if field:
            current[field.group(1).strip()] = field.group(2).strip()
            continue
        body = current.setdefault("body", [])
        if isinstance(body, list):
            body.append(line)
    flush()

    if checkpoints:
        return [checkpoint.to_prompt_item() for checkpoint in checkpoints]
    fallback = ParsedSkillCheckpoint(
        skill_key=skill_key,
        checkpoint_id=f"SKILL:{skill_key}",
        title=f"{skill_key} Skill 检查",
        severity="medium",
        applies_to="**/*",
        check=_compact(content) or "按 Skill 文档要求检查当前 MR。",
        required_evidence="精确文件、行号、源码证据、命中 Skill 检查点、影响说明和建议修改代码。",
        false_positive_patterns="如果源码没有命中 Skill 明确要求的检查点，返回空结果。",
        positive_examples="",
        negative_examples="",
        skip_conditions="只读、测试、示例代码或未命中 Skill 检查点时返回空结果。",
        fix_guidance="",
        source_path=source_path,
        parse_quality="fallback",
    )
    return [fallback.to_prompt_item()]


def _to_checkpoint(skill_key: str, raw: dict[str, str | list[str]], source_path: str) -> ParsedSkillCheckpoint:
    body = raw.get("body", [])
    sections = _extract_sections(body if isinstance(body, list) else [])
    check = str(raw.get("check") or "").strip() or _join_sections(sections, ["检查点", "如何检查", "规范说明", "规则说明"])
    required_evidence = str(raw.get("required_evidence") or raw.get("evidence_required") or "").strip()
    if not required_evidence:
        required_evidence = _join_sections(sections, ["证据要求", "输出要求", "Required Evidence"]) or "精确文件、行号、源码证据和触发条件。"
    false_positive_patterns = str(raw.get("false_positive_patterns") or "").strip() or _join_sections(sections, ["误报模式", "误报排除", "例外"])
    positive_examples = str(raw.get("positive_examples") or "").strip() or _join_sections(sections, ["正例", "正确示例"])
    negative_examples = str(raw.get("negative_examples") or "").strip() or _join_sections(sections, ["反例", "错误示例"])
    skip_conditions = str(raw.get("skip_conditions") or "").strip() or _join_sections(sections, ["跳过条件", "不适用条件", "忽略条件"])
    fix_guidance = str(raw.get("fix_guidance") or "").strip() or _join_sections(sections, ["修复建议", "整改建议"])
    return ParsedSkillCheckpoint(
        skill_key=skill_key,
        checkpoint_id=str(raw["checkpoint_id"]),
        title=str(raw["title"]),
        severity=str(raw.get("severity", "medium")),
        applies_to=str(raw.get("applies_to", "**/*")),
        check=_compact(check),
        required_evidence=_compact(required_evidence),
        false_positive_patterns=_compact(false_positive_patterns),
        positive_examples=_compact(positive_examples),
        negative_examples=_compact(negative_examples),
        skip_conditions=_compact(skip_conditions),
        fix_guidance=_compact(fix_guidance),
        source_path=source_path,
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
    lowered = {key.lower(): key for key in sections}
    for name in names:
        key = lowered.get(name.lower(), name)
        values = sections.get(key) or []
        if values:
            chunks.append(f"{key}：{' '.join(values)}")
    return "\n".join(chunks)


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()
