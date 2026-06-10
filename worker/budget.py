from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BudgetTracker:
    max_wall_seconds: float
    max_llm_calls: int
    started_at: float = field(default_factory=time.monotonic)
    llm_calls: int = 0
    truncated_reason: str | None = None

    @classmethod
    def from_budget(cls, budget: dict[str, Any]) -> "BudgetTracker":
        return cls(
            max_wall_seconds=float(budget.get("max_wall_seconds") or 0),
            max_llm_calls=int(budget.get("max_llm_calls") or 0),
        )

    def charge_llm(self, model: str, in_tokens: int, out_tokens: int) -> None:
        self.llm_calls += 1
        self.should_stop()

    def should_stop(self) -> bool:
        if self.truncated_reason:
            return True
        if self.max_wall_seconds > 0 and time.monotonic() - self.started_at > self.max_wall_seconds:
            self.truncated_reason = "wall_seconds_exceeded"
            return True
        if self.max_llm_calls > 0 and self.llm_calls >= self.max_llm_calls:
            self.truncated_reason = "llm_calls_exceeded"
            return True
        return False

    def snapshot(self) -> dict[str, Any]:
        return {
            "max_wall_seconds": self.max_wall_seconds,
            "max_llm_calls": self.max_llm_calls,
            "wall_seconds": round(max(0.0, time.monotonic() - self.started_at), 3),
            "llm_calls": self.llm_calls,
            "truncated_reason": self.truncated_reason,
        }
