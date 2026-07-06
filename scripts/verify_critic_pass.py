from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mr-backend" / "worker"))

from orchestration.nodes.critic_pass import run_critic_pass


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def event(self, span_id, event_type, message, payload=None):
        self.events.append((str(event_type), str(message)))

    def llm_call(self, *_args, **_kwargs):
        pass


def finding(
    dedupe_hash: str,
    *,
    severity: str = "medium",
    confidence: float = 0.72,
    score: float = 0.8,
    title: str = "低分但成立的问题",
    line: int = 3,
) -> dict:
    return {
        "dedupe_hash": dedupe_hash,
        "severity": severity,
        "confidence": confidence,
        "file_path": "src/main/java/App.java",
        "line_start": line,
        "line_end": line,
        "title": title,
        "problem_description": "desc",
        "recommendation": "fix",
        "evidence": "evidence",
        "suggested_code": "code",
        "covered_rules": ["SEC-INJECT-003"],
        "evidence_score": {"score": score},
        "quality_trace": {"evidence_score": {"score": score}},
    }


def source_files() -> dict[str, str]:
    return {"src/main/java/App.java": "class App {\n  void a() {}\n  void b() {}\n}"}


def assert_rejects_or_confirms_target_findings() -> None:
    prompts: list[str] = []

    def fake_critic(prompt: str) -> dict[str, str]:
        prompts.append(prompt)
        payload = json.loads(prompt)
        title = payload["finding"]["title"]
        if title == "源码不支持的问题":
            return {"verdict": "rejected", "reason": "源码片段无法支持该 finding。", "source": "test"}
        return {"verdict": "confirmed", "reason": "源码片段支持该 finding。", "source": "test"}

    findings = [
        finding("a", severity="high", confidence=0.9, score=0.8, title="源码不支持的问题", line=2),
        finding("b", severity="medium", confidence=0.72, score=0.4, title="低分但成立的问题", line=3),
        finding("c", severity="medium", confidence=0.88, score=0.9, title="证据充足的中风险问题", line=4),
    ]
    reviewed = run_critic_pass(
        findings=findings,
        source_file_contents=source_files(),
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
    assert "critic_verdict" not in by_hash["c"].get("quality_trace", {}), by_hash["c"]
    assert len(prompts) == 2, prompts
    assert "SEC-INJECT-003" not in "\n".join(prompts)
    assert "covered_rules" not in "\n".join(prompts)
    assert "rule_id" not in "\n".join(prompts)


def assert_critic_call_count_is_capped_at_eight() -> None:
    prompts: list[str] = []

    reviewed = run_critic_pass(
        findings=[finding(str(index), severity="high", confidence=0.9, score=0.8, title=f"高风险问题 {index}") for index in range(12)],
        source_file_contents=source_files(),
        config={"review": {"critic": {"max_calls": 20}}},
        recorder=Recorder(),
        span_id="span",
        critic_llm=lambda prompt: prompts.append(prompt) or {"verdict": "confirmed", "reason": "ok", "source": "test"},
    )

    assert len(prompts) == 8, len(prompts)
    reviewed_count = sum(1 for item in reviewed if "critic_verdict" in item.get("quality_trace", {}))
    assert reviewed_count == 8, reviewed_count


def assert_critic_can_be_disabled() -> None:
    prompts: list[str] = []
    reviewed = run_critic_pass(
        findings=[finding("disabled", severity="high", confidence=0.9, score=0.8)],
        source_file_contents=source_files(),
        config={"review": {"critic": {"enabled": False}}},
        recorder=Recorder(),
        span_id="span",
        critic_llm=lambda prompt: prompts.append(prompt) or {"verdict": "confirmed", "reason": "ok", "source": "test"},
    )

    assert prompts == [], prompts
    assert "critic_verdict" not in reviewed[0].get("quality_trace", {}), reviewed


def main() -> None:
    assert_rejects_or_confirms_target_findings()
    assert_critic_call_count_is_capped_at_eight()
    assert_critic_can_be_disabled()
    print(json.dumps({"ok": True, "verified": "critic_pass", "cases": 3}, ensure_ascii=False))


if __name__ == "__main__":
    main()
