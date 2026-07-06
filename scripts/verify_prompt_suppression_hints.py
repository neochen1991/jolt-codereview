from __future__ import annotations

import json
import sys
import types
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mr-backend" / "worker"))

fake_deepagents_runner = types.ModuleType("orchestration.deepagents_runner")
fake_deepagents_runner.run_bounded_deepagent = lambda **_kwargs: {"tool_calls": [], "content": ""}
sys.modules.setdefault("orchestration.deepagents_runner", fake_deepagents_runner)

from prompts.builder import build_prompt
from orchestration.nodes.run_experts import _load_suppression_hints_for_prompt


@dataclass
class ChangedFile:
    filename: str
    status: str = "modified"
    additions: int = 1
    deletions: int = 0
    patch: str = "@@ -1,1 +1,1 @@\n+statement.executeQuery(sql);"


def assert_prompt_injects_suppression_hints_only_when_available() -> None:
    file = ChangedFile("src/main/java/demo/PaymentRepository.java")
    empty_prompt, _ = build_prompt({"agent_id": "security_agent"}, [file], "")
    empty_payload = json.loads(empty_prompt)
    assert "suppression_hints" not in empty_payload, empty_payload.keys()
    assert "suppression_hints" not in empty_payload["input_contract"]["sections"]

    prompt, _ = build_prompt(
        {
            "agent_id": "security_agent",
            "suppression_hints": [
                {
                    "rule_id": "SEC-INJECT-003",
                    "file_glob": "src/main/**",
                    "snippet_hash": "abc123",
                    "snippet_excerpt": "String sql = \"select *\" + userId;",
                    "count": 2,
                }
            ],
        },
        [file],
        "",
    )
    payload = json.loads(prompt)
    assert "suppression_hints" in payload, payload.keys()
    assert "suppression_hints" in payload["input_contract"]["sections"]
    assert payload["suppression_hints"]["items"][0]["rule_id"] == "SEC-INJECT-003"
    assert payload["suppression_hints"]["items"][0]["count"] == 2
    assert "人工判为 FP" in payload["suppression_hints"]["usage_policy"], payload["suppression_hints"]
    assert "suppression_hints" in payload["task"], payload["task"]


class FakeConn:
    def execute(self, _sql, _params):
        return self

    def fetchall(self):
        return [
            {
                "project_id": "project_q10",
                "rule_id": "SEC-INJECT-003",
                "file_glob": "src/main/**",
                "snippet_hash": "abc123",
                "snippet_excerpt": "String sql = \"select *\" + userId;",
                "count": 3,
                "last_marked_at": "2026-07-06T00:00:00Z",
            },
            {
                "project_id": "project_q10",
                "rule_id": "FE-A11Y-003",
                "file_glob": "frontend/src/**",
                "snippet_hash": "def456",
                "snippet_excerpt": "<button />",
                "count": 9,
                "last_marked_at": "2026-07-06T00:00:00Z",
            },
        ]


def assert_run_experts_filters_hints_to_changed_paths() -> None:
    hints = _load_suppression_hints_for_prompt(
        FakeConn(),
        "project_q10",
        [ChangedFile("src/main/java/demo/PaymentRepository.java")],
    )
    assert len(hints) == 1, hints
    assert hints[0]["rule_id"] == "SEC-INJECT-003", hints
    assert hints[0]["count"] == 3, hints


def main() -> None:
    assert_prompt_injects_suppression_hints_only_when_available()
    assert_run_experts_filters_hints_to_changed_paths()
    print(json.dumps({"ok": True, "verified": "prompt_suppression_hints"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
