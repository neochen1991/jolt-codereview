from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ChangeIntent:
    labels: tuple[str, ...]
    semantic_delta: str
    confidence: float
    evidence: tuple[str, ...] = ()

    @classmethod
    def unknown(cls, reason: str = "insufficient deterministic patch evidence") -> "ChangeIntent":
        return cls(("unknown",), "unknown", 0.4, (reason,))

    def to_dict(self) -> dict[str, object]:
        return {
            "labels": list(self.labels),
            "semantic_delta": self.semantic_delta,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
        }


def _changed_lines(patch: str, prefix: str) -> list[str]:
    return [
        line[1:].strip()
        for line in str(patch or "").splitlines()
        if line.startswith(prefix) and not line.startswith(prefix * 3)
    ]


def _is_comment(line: str) -> bool:
    stripped = line.strip()
    return (
        not stripped
        or stripped.startswith(("//", "/*", "*", "*/", "#"))
        or stripped in {'"""', "'''"}
    )


def _is_logging(line: str) -> bool:
    compact = re.sub(r"\s+", "", line).lower()
    return bool(
        re.search(r"\b(?:log|logger)\s*\.\s*(?:trace|debug|info|warn|error)\s*\(", line, re.IGNORECASE)
        or "system.out.print" in compact
        or "system.err.print" in compact
        or re.search(r"\bprint(?:ln)?\s*\(", line, re.IGNORECASE)
    )


def _is_test_path(file_path: str) -> bool:
    path = str(file_path or "").replace("\\", "/").lower()
    name = path.rsplit("/", 1)[-1]
    return "/test/" in path or "/tests/" in path or name.startswith("test_") or name.endswith(("test.java", "tests.java", ".spec.ts", ".test.ts", ".spec.js", ".test.js"))


def classify_change_intent(file_path: str, patch: str, *, status: str = "modified") -> ChangeIntent:
    added = _changed_lines(patch, "+")
    deleted = _changed_lines(patch, "-")
    changed = [*added, *deleted]
    if _is_test_path(file_path):
        return ChangeIntent(("test_only",), "test_change", 0.98, ("changed file is in a test path",))
    if str(status or "").lower() in {"renamed", "rename", "moved", "copied"}:
        return ChangeIntent(("rename_or_move",), "behavior_preserving", 0.9, (f"git change status is {status}",))
    if not changed:
        return ChangeIntent.unknown("patch contains no added or deleted source lines")
    if all(_is_comment(line) for line in changed):
        return ChangeIntent(("comment_or_documentation",), "behavior_preserving", 0.98, ("all changed lines are comments or whitespace",))

    code_changes = [line for line in changed if not _is_comment(line) and not _is_logging(line)]
    logging_changes = [line for line in changed if _is_logging(line)]
    if logging_changes and not code_changes:
        return ChangeIntent(("logging_only",), "behavior_preserving", 0.96, ("all executable changed lines are logging calls",))
    if logging_changes and code_changes:
        return ChangeIntent(("mixed",), "unknown", 0.65, ("logging and executable behavior changed together",))
    return ChangeIntent(("behavior_change",), "behavior_changed", 0.8, ("patch changes executable non-logging source",))
