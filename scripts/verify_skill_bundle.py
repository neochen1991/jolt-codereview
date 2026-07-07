from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "mr-backend" / "worker"
sys.path.insert(0, str(WORKER))

from rules.skill_checkpoint_parser import parse_skill_checkpoints


REQUIRED_FIELDS = ["check", "required_evidence", "false_positive_patterns", "fix_guidance"]


def _read(path: Path) -> str:
    return path.read_text("utf-8")


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    fields: dict[str, str] = {}
    for raw in text[4:end].splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        fields[key.strip()] = value.strip().strip('"')
    return fields


def _suspicious_field_bullets(path: Path, text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    current_section = ""
    for index, raw in enumerate(text.splitlines(), start=1):
        section = re.match(r"^###\s+(.+)$", raw.strip())
        if section:
            current_section = section.group(1).strip()
            continue
        if current_section not in {"误报模式", "误报排除", "例外", "证据要求", "输出要求"}:
            continue
        stripped = raw.strip()
        # The parser treats "- system:refund:config ..." as a field named "system".
        if re.match(r"^-\s*[A-Za-z_][A-Za-z0-9_]*:[^\s:：]+", stripped):
            findings.append(
                {
                    "path": str(path),
                    "line": index,
                    "section": current_section,
                    "message": "bullet looks like parser field syntax; rewrite as natural language, e.g. '永久配置 key，例如 system:refund:config'",
                    "text": stripped,
                }
            )
    return findings


def validate_skill_bundle(skill_dir: Path) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    previews: list[dict[str, Any]] = []

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        failures.append({"path": str(skill_md), "message": "missing SKILL.md"})
        return {"ok": False, "failures": failures, "warnings": warnings, "checkpoints": previews}

    frontmatter = _frontmatter(_read(skill_md))
    for field in ["name", "description"]:
        if not frontmatter.get(field):
            failures.append({"path": str(skill_md), "message": f"missing frontmatter field: {field}"})

    skill_key = frontmatter.get("name") or skill_dir.name
    sources = [skill_md]
    references = sorted((skill_dir / "references").glob("**/*")) if (skill_dir / "references").exists() else []
    sources.extend(path for path in references if path.is_file() and path.suffix.lower() in {".md", ".mdx", ".txt"})

    seen_ids: dict[str, str] = {}
    for source in sources:
        text = _read(source)
        warnings.extend(_suspicious_field_bullets(source, text))
        checkpoints = parse_skill_checkpoints(skill_key, text, source_path=str(source.relative_to(skill_dir)))
        structured = [item for item in checkpoints if str(item.get("parse_quality") or "") == "structured"]
        for checkpoint in structured:
            checkpoint_id = str(checkpoint.get("checkpoint_id") or "")
            if checkpoint_id in seen_ids:
                failures.append(
                    {
                        "path": str(source),
                        "message": f"duplicate checkpoint_id {checkpoint_id}; already defined in {seen_ids[checkpoint_id]}",
                    }
                )
            seen_ids[checkpoint_id] = str(source)
            missing = [field for field in REQUIRED_FIELDS if not str(checkpoint.get(field) or "").strip()]
            if missing:
                failures.append(
                    {
                        "path": str(source),
                        "checkpoint_id": checkpoint_id,
                        "message": f"checkpoint missing required fields: {', '.join(missing)}",
                    }
                )
            previews.append(
                {
                    "checkpoint_id": checkpoint_id,
                    "title": checkpoint.get("title"),
                    "source_path": checkpoint.get("source_path"),
                    "required_evidence": checkpoint.get("required_evidence"),
                    "false_positive_patterns": checkpoint.get("false_positive_patterns"),
                    "fix_guidance": checkpoint.get("fix_guidance"),
                }
            )

    if not previews:
        failures.append({"path": str(skill_dir), "message": "no structured checkpoints parsed from SKILL.md or references"})

    return {
        "ok": not failures and not warnings,
        "skill_dir": str(skill_dir),
        "failures": failures,
        "warnings": warnings,
        "checkpoints": previews,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("skill_dir")
    parser.add_argument("--allow-warnings", action="store_true")
    args = parser.parse_args()

    report = validate_skill_bundle(Path(args.skill_dir))
    if args.allow_warnings and not report["failures"]:
        report["ok"] = True
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
