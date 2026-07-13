from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class SourceRange:
    file_path: str
    line_start: int
    line_end: int
    content_hash: str


@dataclass(frozen=True)
class DependencyRef:
    relation: str
    symbol_id: str
    source: SourceRange
    confidence: Literal["typed", "syntax", "heuristic"]
    source_text: str = ""


@dataclass(frozen=True)
class ContextUnit:
    unit_id: str
    hunk_ids: tuple[str, ...]
    primary_source: SourceRange
    changed_symbol_ids: tuple[str, ...]
    source_text: str
    patch_text: str
    dependencies: tuple[DependencyRef, ...] = field(default_factory=tuple)
    skill_checkpoint_ids: tuple[str, ...] = field(default_factory=tuple)
    token_estimate: int = 0
    unresolved_dependencies: tuple[str, ...] = field(default_factory=tuple)
    fallback_reason: str = ""
    context_hash: str = ""
    execution_status: str = "pending"

    def to_prompt_item(self) -> dict[str, object]:
        return {
            "unit_id": self.unit_id,
            "hunk_ids": list(self.hunk_ids),
            "file_path": self.primary_source.file_path,
            "line_start": self.primary_source.line_start,
            "line_end": self.primary_source.line_end,
            "changed_symbol_ids": list(self.changed_symbol_ids),
            "source_text": self.source_text,
            "patch_text": self.patch_text,
            "dependencies": [
                {
                    "relation": item.relation,
                    "symbol_id": item.symbol_id,
                    "file_path": item.source.file_path,
                    "line_start": item.source.line_start,
                    "line_end": item.source.line_end,
                    "confidence": item.confidence,
                    "source_text": item.source_text,
                }
                for item in self.dependencies
            ],
            "skill_checkpoint_ids": list(self.skill_checkpoint_ids),
            "unresolved_dependencies": list(self.unresolved_dependencies),
            "fallback_reason": self.fallback_reason,
            "context_hash": self.context_hash,
        }
