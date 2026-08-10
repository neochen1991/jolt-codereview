from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from diff.slicer import extract_added_lines


def canonical_review_path(value: str) -> str:
    path = str(value or "").strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return "/".join(part for part in path.split("/") if part and part != ".")


@dataclass(frozen=True)
class DiffScope:
    changed_files: set[str]
    added_lines: dict[str, set[int]]
    added_text: dict[str, dict[int, str]]
    patch_health: dict[str, str]
    path_aliases: dict[str, str]

    @classmethod
    def from_files(cls, files: list[Any]) -> "DiffScope":
        changed_files: set[str] = set()
        added_lines: dict[str, set[int]] = {}
        added_text: dict[str, dict[int, str]] = {}
        patch_health: dict[str, str] = {}
        path_aliases: dict[str, str] = {}
        for changed in files or []:
            raw_path = str(getattr(changed, "filename", "") or "")
            canonical_path = canonical_review_path(raw_path)
            if not canonical_path:
                continue
            changed_files.add(canonical_path)
            for alias in {raw_path, canonical_path, f"a/{canonical_path}", f"b/{canonical_path}"}:
                normalized_alias = canonical_review_path(alias)
                if normalized_alias:
                    path_aliases[normalized_alias] = canonical_path
            patch = str(getattr(changed, "patch", "") or "")
            extracted = [(int(line), str(text or "")) for line, text in extract_added_lines(patch) if line is not None]
            added_lines[canonical_path] = {line for line, _ in extracted}
            added_text[canonical_path] = {line: text for line, text in extracted}
            if not patch.strip():
                patch_health[canonical_path] = "missing"
            elif "@@" not in patch:
                patch_health[canonical_path] = "malformed"
            else:
                patch_health[canonical_path] = "healthy"
        return cls(changed_files, added_lines, added_text, patch_health, path_aliases)

    def resolve_path(self, value: str) -> str | None:
        normalized = canonical_review_path(value)
        resolved = self.path_aliases.get(normalized, normalized)
        return resolved if resolved in self.changed_files else None

    def line_scope_reason(self, file_path: str, line: int | None, *, scope_kind: str = "line") -> str | None:
        resolved = self.resolve_path(file_path)
        if resolved is None:
            return "file_not_changed_by_diff"
        if scope_kind == "file":
            return None
        if self.patch_health.get(resolved) != "healthy":
            return "diff_patch_unavailable"
        if line is None or int(line) <= 0:
            return "missing_diff_line"
        if int(line) not in self.added_lines.get(resolved, set()):
            return "line_not_added_by_diff"
        return None

    def normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        resolved = self.resolve_path(str(item.get("file_path") or ""))
        return {**item, "file_path": resolved} if resolved else dict(item)
