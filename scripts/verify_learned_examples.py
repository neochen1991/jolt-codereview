from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mr-backend" / "worker"))

from prompts.builder import build_prompt
from prompts.example_retriever import retrieve_examples


@dataclass
class ChangedFile:
    filename: str
    status: str = "modified"
    additions: int = 1
    deletions: int = 0
    patch: str = "@@ -1,1 +1,1 @@\n+String sql = \"select * from users where id=\" + userId;"


def assert_empty_gold_returns_no_examples() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "empty.jsonl"
        empty.write_text("", "utf-8")
        examples = retrieve_examples(
            "security_agent",
            [ChangedFile("src/main/java/com/acme/UserController.java")],
            gold_paths=[empty],
            feedback_rows=[],
        )
        assert examples == [], examples


def assert_gold_examples_are_retrieved_by_agent_language_and_category() -> None:
    examples = retrieve_examples(
        "security_agent",
        [ChangedFile("src/main/java/com/acme/payment/PaymentController.java")],
        k=3,
        feedback_rows=[],
    )
    assert examples, "expected security examples from evaluation gold set"
    assert all(item["source"] == "gold" for item in examples), examples
    assert any(item["label"] == "expected_finding" for item in examples), examples
    assert any(item["file_path"].endswith(".java") for item in examples), examples


def assert_real_finding_context_enriches_positive_examples() -> None:
    examples = retrieve_examples(
        "redis_agent",
        [ChangedFile("src/main/java/com/acme/payment/infra/RedisPaymentCache.java")],
        k=3,
        feedback_rows=[],
    )
    redis_example = next(
        item
        for item in examples
        if item["label"] == "expected_finding" and item["rule_id"] == "REDIS-TTL-002"
    )
    assert redis_example["source"] == "gold", redis_example
    assert redis_example["title"] == "Redis 缓存写入缺少 TTL", redis_example
    assert "redisTemplate.opsForValue().set" in redis_example["snippet"], redis_example
    assert "过期时间" in redis_example["problem_description"], redis_example
    assert "设置明确过期时间" in redis_example["recommendation"], redis_example


def assert_feedback_false_positive_is_included_as_negative_example() -> None:
    examples = retrieve_examples(
        "security_agent",
        [ChangedFile("src/main/java/com/acme/payment/PaymentController.java")],
        k=3,
        feedback_rows=[
            {
                "feedback_type": "false_positive",
                "rule_id": "SEC-INJECT-003",
                "file_path": "src/main/java/com/acme/payment/PaymentController.java",
                "line_start": 42,
                "severity": "high",
                "evidence": "历史用户确认该 SQL 片段并非注入风险。",
                "created_at": "2026-06-17T00:00:00Z",
            }
        ],
    )
    negative = [item for item in examples if item["label"] == "skip_false_positive"]
    assert len(negative) == 1, examples
    assert negative[0]["source"] == "feedback", negative


def assert_boundary_example_is_included_to_protect_expert_scope() -> None:
    examples = retrieve_examples(
        "security_agent",
        [ChangedFile("src/main/java/com/acme/payment/PaymentController.java")],
        k=3,
        feedback_rows=[
            {
                "feedback_type": "false_positive",
                "rule_id": "SEC-INJECT-003",
                "file_path": "src/main/java/com/acme/payment/PaymentController.java",
                "line_start": 42,
                "severity": "high",
                "evidence": "历史用户确认该 SQL 片段并非注入风险。",
                "created_at": "2026-06-17T00:00:00Z",
            }
        ],
    )
    labels = {item["label"] for item in examples}
    assert {"expected_finding", "skip_false_positive", "boundary_other_expert"}.issubset(labels), examples
    boundary = next(item for item in examples if item["label"] == "boundary_other_expert")
    assert boundary["source"] == "gold", boundary
    assert not str(boundary["rule_id"]).startswith("SEC-"), boundary


def assert_prompt_injects_learned_examples_only_when_available() -> None:
    file = ChangedFile("src/main/java/com/acme/payment/PaymentController.java")
    empty_prompt, _ = build_prompt({"agent_id": "security_agent"}, [file], "")
    empty_payload = json.loads(empty_prompt)
    assert "learned_examples" not in empty_payload, empty_payload.keys()
    assert "learned_examples" not in empty_payload["input_contract"]["sections"]

    prompt, _ = build_prompt(
        {
            "agent_id": "security_agent",
            "learned_examples": [
                {
                    "source": "gold",
                    "label": "expected_finding",
                    "rule_id": "SEC-INJECT-003",
                    "category": "injection",
                    "severity": "high",
                    "file_path": file.filename,
                    "line": 42,
                    "snippet": "executeQuery / userId",
                    "evidence_keywords": ["executeQuery", "userId"],
                },
                {
                    "source": "gold",
                    "label": "boundary_other_expert",
                    "rule_id": "PERF-QUERY-001",
                    "category": "UNBOUNDED_QUERY",
                    "severity": "medium",
                    "file_path": file.filename,
                    "line": 44,
                    "snippet": "repository.findAll()",
                    "evidence_keywords": ["findAll"],
                }
            ],
        },
        [file],
        "",
    )
    payload = json.loads(prompt)
    assert "learned_examples" in payload, payload.keys()
    assert "learned_examples" in payload["input_contract"]["sections"]
    assert payload["learned_examples"]["items"][0]["label"] == "expected_finding"
    assert payload["learned_examples"]["items"][1]["label"] == "boundary_other_expert"
    assert "boundary_other_expert 样例用于明确专家职责边界" in payload["task"], payload["task"]


def assert_no_manual_prompt_example_files() -> None:
    prompt_dir = ROOT / "worker" / "prompts"
    manual_files = [
        path.relative_to(ROOT).as_posix()
        for path in prompt_dir.rglob("*")
        if path.is_file() and path.suffix == ".jsonl" and "examples" in path.as_posix().lower()
    ]
    manual_dirs = [path.relative_to(ROOT).as_posix() for path in prompt_dir.rglob("examples") if path.is_dir()]
    assert not manual_files, manual_files
    assert not manual_dirs, manual_dirs


def main() -> None:
    assert_empty_gold_returns_no_examples()
    assert_gold_examples_are_retrieved_by_agent_language_and_category()
    assert_real_finding_context_enriches_positive_examples()
    assert_feedback_false_positive_is_included_as_negative_example()
    assert_boundary_example_is_included_to_protect_expert_scope()
    assert_prompt_injects_learned_examples_only_when_available()
    assert_no_manual_prompt_example_files()
    print(json.dumps({"ok": True, "verified": "learned_examples"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
