from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RULE_LITERAL_RE = re.compile(r"""if\s+[^:\n]*(?:==|!=| in )\s*["'][A-Z][A-Z0-9]+-[A-Z0-9:-]+-\d{3}["']""")
CHINESE_TEXT_BRANCH_RE = re.compile(r"""if\s+["'][^"']*[\u4e00-\u9fff][^"']*["']\s+in\s+[^:\n]*(?:text|finding|item|title|evidence)""")
RULE_SET_RE = re.compile(r"""(?:set|frozenset)\s*\(\s*\{[^}]*[A-Z][A-Z0-9]+-[A-Z0-9:-]+-\d{3}""", re.DOTALL)


def scan_file(path: Path) -> list[dict[str, object]]:
    text = path.read_text("utf-8")
    violations: list[dict[str, object]] = []
    for name, pattern in [
        ("rule_literal_branch", RULE_LITERAL_RE),
        ("chinese_keyword_branch", CHINESE_TEXT_BRANCH_RE),
        ("rule_set_literal", RULE_SET_RE),
    ]:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            violations.append({"kind": name, "file": str(path.relative_to(ROOT)), "line": line, "snippet": match.group(0)[:160]})
    return violations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-legacy", action="store_true", help="Also fail on legacy nodes/judge_findings.py debt.")
    args = parser.parse_args()

    targets = [ROOT / "worker" / "orchestration" / "judging"]
    if args.include_legacy:
        targets.append(ROOT / "worker" / "orchestration" / "nodes" / "judge_findings.py")

    violations: list[dict[str, object]] = []
    for target in targets:
        if target.is_dir():
            for path in target.rglob("*.py"):
                violations.extend(scan_file(path))
        elif target.exists():
            violations.extend(scan_file(target))

    prompt_examples = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "worker" / "prompts").rglob("*")
        if path.is_file() and "examples" in path.name.lower() and path.suffix == ".jsonl"
    ]
    for path in prompt_examples:
        violations.append({"kind": "manual_prompt_examples", "file": path, "line": 1, "snippet": "manual examples jsonl"})

    if violations:
        print(json.dumps({"ok": False, "violations": violations}, ensure_ascii=False, indent=2))
        raise SystemExit(1)
    print(json.dumps({"ok": True, "scanned": [str(target.relative_to(ROOT)) for target in targets]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
