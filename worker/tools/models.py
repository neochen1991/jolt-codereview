from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolObservation:
    tool_name: str
    rule_id: str | None
    severity: str
    confidence: float
    file_path: str
    line_start: int | None
    line_end: int | None
    message: str
    raw_artifact_id: str | None = None
    adopted_by_agent: str | None = None
    adoption_state: str = "candidate"

    def to_prompt_item(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "confidence": self.confidence,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "message": self.message,
            "raw_artifact_id": self.raw_artifact_id,
            "adoption_state": self.adoption_state,
            "adopted_by_agent": self.adopted_by_agent,
        }
