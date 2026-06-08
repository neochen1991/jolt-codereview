from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExpertProfile:
    agent_key: str
    display_name: str
    role_profile: str
    responsibility_scope: str
    excluded_scope: str
    enabled: bool = True
    min_confidence: float = 0.75
    max_findings: int = 8
    max_llm_calls: int = 4
    max_tool_calls: int = 8
    output_schema_version: str = "finding_v1"

    def to_agent_config(self) -> dict:
        skill_by_agent = {
            "security_agent": "security-review",
            "performance_agent": "performance-review",
            "coding_agent": "coding-review",
            "ddd_agent": "ddd-design-review",
            "frontend_agent": "frontend-review",
            "test_agent": "test-review",
            "redis_agent": "redis-review",
            "backend_agent": "backend-review",
            "dependency_agent": "dependency-review",
            "database_agent": "database-review",
        }
        return {
            "agent_id": self.agent_key,
            "display_name": self.display_name,
            "applies_to": {
                "persona": self.role_profile,
                "review_scope": self.responsibility_scope,
                "excluded_scope": self.excluded_scope,
                "exclusive_scope": self.agent_key.replace("_agent", ""),
            },
            "tools": [],
            "skills": [skill_by_agent.get(self.agent_key, self.agent_key.replace("_", "-").replace("-agent", "-review"))],
            "rule_sets": [],
            "min_confidence": self.min_confidence,
            "max_findings_per_mr": self.max_findings,
            "max_llm_calls": self.max_llm_calls,
            "max_tool_calls": self.max_tool_calls,
            "output_schema_version": self.output_schema_version,
        }
