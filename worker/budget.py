from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


# USD per 1K tokens. MiniMax-M2.7 is configured as the local/default review model.
LLM_PRICING = {
    "MiniMax-M2.7": {"in": 0.0010, "out": 0.0030},
    "deepseek-chat": {"in": 0.00014, "out": 0.00028},
    "qwen-max": {"in": 0.0020, "out": 0.0060},
    "claude-sonnet-4-6": {"in": 0.0030, "out": 0.0150},
    "gpt-4o-mini": {"in": 0.00015, "out": 0.00060},
}


@dataclass
class BudgetTracker:
    max_wall_seconds: float
    max_cost_usd: float
    max_llm_calls: int
    started_at: float = field(default_factory=time.monotonic)
    cost_usd: float = 0.0
    llm_calls: int = 0
    truncated_reason: str | None = None

    @classmethod
    def from_budget(cls, budget: dict[str, Any]) -> "BudgetTracker":
        return cls(
            max_wall_seconds=float(budget.get("max_wall_seconds") or 0),
            max_cost_usd=float(budget.get("max_cost_usd") or 0),
            max_llm_calls=int(budget.get("max_llm_calls") or 0),
        )

    def charge_llm(self, model: str, in_tokens: int, out_tokens: int) -> None:
        price = LLM_PRICING.get(model) or LLM_PRICING.get(model.lower()) or {"in": 0.001, "out": 0.003}
        self.cost_usd += max(0, in_tokens) * price["in"] / 1000 + max(0, out_tokens) * price["out"] / 1000
        self.llm_calls += 1
        self.should_stop()

    def should_stop(self) -> bool:
        if self.truncated_reason:
            return True
        if self.max_wall_seconds > 0 and time.monotonic() - self.started_at > self.max_wall_seconds:
            self.truncated_reason = "wall_seconds_exceeded"
            return True
        if self.max_cost_usd > 0 and self.cost_usd > self.max_cost_usd:
            self.truncated_reason = "cost_usd_exceeded"
            return True
        if self.max_llm_calls > 0 and self.llm_calls >= self.max_llm_calls:
            self.truncated_reason = "llm_calls_exceeded"
            return True
        return False

    def snapshot(self) -> dict[str, Any]:
        return {
            "max_wall_seconds": self.max_wall_seconds,
            "max_cost_usd": round(self.max_cost_usd, 6),
            "max_llm_calls": self.max_llm_calls,
            "wall_seconds": round(max(0.0, time.monotonic() - self.started_at), 3),
            "cost_usd": round(self.cost_usd, 6),
            "llm_calls": self.llm_calls,
            "truncated_reason": self.truncated_reason,
        }
