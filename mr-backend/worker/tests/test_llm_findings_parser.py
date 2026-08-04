from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

from llm.client import build_json_repair_messages, collect_openai_sse_lines, parse_llm_findings, response_needs_json_repair  # noqa: E402
from llm.exchange import InMemoryExchangeStore, execute_chat_exchange  # noqa: E402


FILES = [SimpleNamespace(filename="src/App.java")]


def _finding(**overrides) -> dict:
    return {
        "severity": "high",
        "confidence": 0.9,
        "file_path": "src/App.java",
        "line_start": 12,
        "line_end": 12,
        "title": "空值处理缺失",
        "problem_description": "调用结果可能为空。",
        "trigger_condition": "依赖返回 null。",
        "impact": "请求失败。",
        "semantic_evidence": [],
        "recommendation": "增加校验。",
        "suggested_code": "if (value == null) return;",
        "evidence": "第12行直接解引用。",
        "covered_rules": ["null-safety"],
        "skipped_rules": [],
        **overrides,
    }


def test_parser_accepts_json_object_and_legacy_array() -> None:
    metrics: dict = {}
    wrapped = parse_llm_findings("agent", json.dumps({"findings": [_finding()]}, ensure_ascii=False), FILES, metrics=metrics)
    legacy = parse_llm_findings("agent", json.dumps([_finding()], ensure_ascii=False), FILES)

    assert len(wrapped) == 1
    assert len(legacy) == 1
    assert metrics["candidate_count"] == 1
    assert metrics["accepted_count"] == 1
    assert metrics["parse_status"] == "complete"


def test_parser_reports_drop_reasons() -> None:
    metrics: dict = {}
    content = json.dumps(
        {
            "findings": [
                _finding(file_path="src/Missing.java"),
                _finding(line_start=None),
                "not-an-object",
            ]
        },
        ensure_ascii=False,
    )

    findings = parse_llm_findings("agent", content, FILES, metrics=metrics)

    assert findings == []
    assert metrics["candidate_count"] == 3
    assert metrics["dropped_invalid_file"] == 1
    assert metrics["dropped_invalid_line"] == 1
    assert metrics["dropped_non_object"] == 1


def test_stream_collector_retains_reasoning_and_finish_reason() -> None:
    response = collect_openai_sse_lines(
        [
            'data: {"choices":[{"delta":{"reasoning_content":"分析"}}]}',
            'data: {"choices":[{"delta":{"content":"{\\"findings\\":[]}"},"finish_reason":"length"}],"usage":{"completion_tokens":32}}',
            "data: [DONE]",
        ],
        0,
    )

    message = response["choices"][0]["message"]
    assert message["reasoning_content"] == "分析"
    assert response["choices"][0]["finish_reason"] == "length"
    assert response_needs_json_repair(response) is True


def test_json_repair_instruction_preserves_original_context_and_requests_shorter_complete_output() -> None:
    messages = [{"role": "system", "content": "rules"}, {"role": "user", "content": "context"}]
    repaired = build_json_repair_messages(messages)

    assert repaired[:2] == messages
    assert repaired[-1]["role"] == "user"
    assert "findings" in repaired[-1]["content"]
    assert "完整" in repaired[-1]["content"]
    assert "精简" in repaired[-1]["content"]


class _Recorder:
    def __init__(self) -> None:
        self.run_id = "run"
        self.calls: list[dict] = []

    def llm_call(self, *args, **kwargs) -> None:
        self.calls.append({"args": args, "kwargs": kwargs})


def test_exchange_logs_finish_reason_and_response_sizes() -> None:
    recorder = _Recorder()
    response = {
        "id": "resp",
        "choices": [{"message": {"content": '{"findings":[]}', "reasoning_content": "分析过程"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }

    execute_chat_exchange(
        recorder=recorder,
        span_id="span",
        operation="expert",
        agent_id="agent",
        context_unit_id="unit",
        checkpoint_id="cp",
        head_sha="head",
        provider="gateway",
        model="glm-5.2",
        prompt="prompt",
        messages=[{"role": "user", "content": "prompt"}],
        temperature=0.1,
        replay_mode="off",
        store=InMemoryExchangeStore(),
        invoke=lambda _seed: response,
    )

    composition = recorder.calls[0]["kwargs"]["input_composition"]
    assert composition["finish_reason"] == "stop"
    assert composition["response_content_chars"] == len('{"findings":[]}')
    assert composition["reasoning_content_chars"] == len("分析过程")


if __name__ == "__main__":
    test_parser_accepts_json_object_and_legacy_array()
    test_parser_reports_drop_reasons()
    test_stream_collector_retains_reasoning_and_finish_reason()
    test_json_repair_instruction_preserves_original_context_and_requests_shorter_complete_output()
    test_exchange_logs_finish_reason_and_response_sizes()
    print("LLM finding parser tests passed")
