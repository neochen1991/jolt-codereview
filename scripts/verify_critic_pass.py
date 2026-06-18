from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from orchestration.nodes.critic_pass import run_critic_pass


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def event(self, span_id, event_type, message, payload=None):
        self.events.append((str(event_type), str(message)))

    def llm_call(self, *_args, **_kwargs):
        pass


def main() -> None:
    prompts: list[str] = []

    def fake_critic(prompt: str) -> dict[str, str]:
        prompts.append(prompt)
        payload = json.loads(prompt)
        title = payload["finding"]["title"]
        if title == "源码不支持的问题":
            return {"verdict": "rejected", "reason": "源码片段无法支持该 finding。", "source": "test"}
        return {"verdict": "confirmed", "reason": "源码片段支持该 finding。", "source": "test"}

    findings = [
        {
            "dedupe_hash": "a",
            "severity": "high",
            "confidence": 0.9,
            "file_path": "src/main/java/App.java",
            "line_start": 2,
            "line_end": 2,
            "title": "源码不支持的问题",
            "problem_description": "desc",
            "recommendation": "fix",
            "evidence": "evidence",
            "suggested_code": "code",
            "covered_rules": ["SEC-INJECT-003"],
            "evidence_score": {"total_score": 0.8},
            "quality_trace": {"evidence_score": {"total_score": 0.8}},
        },
        {
            "dedupe_hash": "b",
            "severity": "medium",
            "confidence": 0.72,
            "file_path": "src/main/java/App.java",
            "line_start": 3,
            "line_end": 3,
            "title": "低分但成立的问题",
            "problem_description": "desc",
            "recommendation": "fix",
            "evidence": "evidence",
            "suggested_code": "code",
            "evidence_score": {"total_score": 0.4},
            "quality_trace": {"evidence_score": {"total_score": 0.4}},
        },
    ]
    reviewed = run_critic_pass(
        findings=findings,
        source_file_contents={"src/main/java/App.java": "class App {\n  void a() {}\n  void b() {}\n}"},
        config={},
        recorder=Recorder(),
        span_id="span",
        critic_llm=fake_critic,
    )
    by_hash = {item["dedupe_hash"]: item for item in reviewed}
    assert by_hash["a"]["severity"] == "medium", by_hash["a"]
    assert round(by_hash["a"]["confidence"], 3) == 0.63, by_hash["a"]
    assert by_hash["a"]["quality_trace"]["critic_verdict"]["verdict"] == "rejected"
    assert by_hash["b"]["severity"] == "medium", by_hash["b"]
    assert by_hash["b"]["quality_trace"]["critic_verdict"]["verdict"] == "confirmed"
    assert len(prompts) == 2, prompts
    assert "SEC-INJECT-003" not in "\n".join(prompts)
    assert "covered_rules" not in "\n".join(prompts)
    assert "rule_id" not in "\n".join(prompts)
    print(json.dumps({"ok": True, "verified": "critic_pass", "prompt_count": len(prompts)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
